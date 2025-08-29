import os
import json
import re
import hashlib
from typing import List
from dotenv import load_dotenv
from pinecone import Pinecone, ServerlessSpec
from openai import OpenAI

# Load environment variables from .env file
load_dotenv()

# Check required environment variables
required_vars = ["OPENAI_API_KEY", "PINECONE_API_KEY"]
missing_vars = [var for var in required_vars if not os.getenv(var)]

if missing_vars:
    print(f"❌ Missing required environment variables: {', '.join(missing_vars)}")
    print("Please create a .env file in the patient-api directory with:")
    for var in missing_vars:
        print(f"  {var}=your_value_here")
    exit(1)

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
PINECONE_API_KEY = os.environ["PINECONE_API_KEY"]
INDEX_NAME = os.getenv("PINECONE_INDEX", "oncolife-rag")
CLOUD = os.getenv("PINECONE_CLOUD", "aws")
REGION = os.getenv("PINECONE_REGION", "us-west-2")  # Changed to us-west-2
EMBED_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBED_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))

print(f"🔧 Configuration:")
print(f"  Index: {INDEX_NAME}")
print(f"  Cloud: {CLOUD}")
print(f"  Region: {REGION}")
print(f"  Embedding Model: {EMBED_MODEL}")
print(f"  Dimension: {EMBED_DIM}")

client = OpenAI(api_key=OPENAI_API_KEY)
pc = Pinecone(api_key=PINECONE_API_KEY)

# Create index if needed
if INDEX_NAME not in [i.name for i in pc.list_indexes()]:
    print(f"[INGEST] Creating Pinecone index '{INDEX_NAME}' (dim={EMBED_DIM}) in {CLOUD}:{REGION}")
    pc.create_index(
        name=INDEX_NAME,
        dimension=EMBED_DIM,
        metric="cosine",
        spec=ServerlessSpec(cloud=CLOUD, region=REGION),
    )
index = pc.Index(INDEX_NAME)


def embed_texts(texts: List[str]) -> List[List[float]]:
    r = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [d.embedding for d in r.data]


def stable_id(prefix: str, payload: str) -> str:
    return hashlib.md5(f"{prefix}:{payload}".encode()).hexdigest()


def chunk_text(text: str, max_chunk_size: int = 1000) -> List[str]:
    """Split text into chunks that fit within Pinecone's size limits."""
    chunks = []
    lines = text.split('\n')
    current_chunk = ""
    
    for line in lines:
        # Check if adding this line would exceed the limit
        test_chunk = current_chunk + line + '\n'
        if len(test_chunk.encode('utf-8')) > max_chunk_size:
            # Save current chunk if it has content
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
            # Start new chunk with current line
            current_chunk = line + '\n'
        else:
            current_chunk = test_chunk
    
    # Add the last chunk if it has content
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    # If we still have chunks that are too large, split them further
    final_chunks = []
    for chunk in chunks:
        if len(chunk.encode('utf-8')) > max_chunk_size:
            # Split by sentences or words if still too large
            words = chunk.split()
            temp_chunk = ""
            for word in words:
                if len((temp_chunk + word + " ").encode('utf-8')) > max_chunk_size:
                    if temp_chunk.strip():
                        final_chunks.append(temp_chunk.strip())
                    temp_chunk = word + " "
                else:
                    temp_chunk += word + " "
            if temp_chunk.strip():
                final_chunks.append(temp_chunk.strip())
        else:
            final_chunks.append(chunk)
    
    return final_chunks


# ---- Ingest CTCAE triage guidance ----
def ingest_ctcae(path="model_inputs/rag/CTCAE.json", version="CTCAE v5"):
    with open(path, "r") as f:
        data = json.load(f)
    
    # Create much smaller, focused chunks for each symptom-grade combination
    items = []
    for category, symptoms in data.items():
        for symptom_name, grades in symptoms.items():
            for grade, description in grades.items():
                if description:  # Only add non-empty descriptions
                    # Create a focused chunk for each grade
                    text = f"Symptom: {symptom_name}\nCategory: {category}\nGrade {grade}: {description}"
                    items.append(text)
    
    print(f"[INGEST] Created {len(items)} focused CTCAE chunks from {path}")
    
    # Process in smaller batches to avoid memory issues
    batch_size = 100
    total_vectors = 0
    
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        print(f"[INGEST] Processing batch {i//batch_size + 1}/{(len(items) + batch_size - 1)//batch_size} ({len(batch)} items)")
        
        # Create embeddings for this batch
        embs = embed_texts(batch)
        vectors = []
        
        for text, emb in zip(batch, embs):
            # Extract symptom name for metadata
            symptom_match = re.search(r"Symptom:\s*([^\n]+)", text)
            symptom = symptom_match.group(1).strip().lower() if symptom_match else "general"
            
            vid = stable_id("ctcae", text[:200])
            vectors.append({
                "id": vid,
                "values": emb,
                "metadata": {
                    "type": "ctcae",
                    "symptoms": [symptom],
                    "version": version,
                    "source": "ctcae",
                    "text": text,
                }
            })
        
        # Upsert this batch
        index.upsert(vectors=vectors)
        total_vectors += len(vectors)
        print(f"[INGEST] Upserted batch: {len(vectors)} vectors")
    
    print(f"[INGEST] Total CTCAE vectors ingested: {total_vectors}")


# ---- Ingest Question bank ----
def ingest_questions(path="model_inputs/rag/questions.json"):
    with open(path, "r") as f:
        q = json.load(f)  # list of {id, text, symptom, phase, ...}
    texts = [item["text"] for item in q]
    print(f"[INGEST] Embedding {len(texts)} questions from {path}")
    embs = embed_texts(texts)
    vectors = []
    for item, emb in zip(q, embs):
        vid = stable_id("question", str(item.get("id", "")))
        vectors.append({
            "id": vid,
            "values": emb,
            "metadata": {
                "type": "question",
                "symptoms": [item.get("symptom", "general").lower()],
                "phase": item.get("phase", ""),
                "qid": item.get("id", ""),
                "text": item["text"],
            }
        })
    index.upsert(vectors=vectors)
    print(f"[INGEST] Ingested question chunks: {len(vectors)}")


# ---- Ingest Triage Knowledge Base ----
def ingest_triage_kb(path="model_inputs/rag/triage_kb_v2.json", version="triage-rules.v2"):
    """Ingest triage knowledge base rules, chunking by individual rules for better retrieval."""
    with open(path, "r") as f:
        data = json.load(f)
    
    # Extract rules and create focused chunks for each rule
    rules = data.get("rules", [])
    items = []
    
    for rule in rules:
        # Create a comprehensive chunk for each rule
        symptom = rule.get("symptom", "unknown")
        attribute = rule.get("attribute", "unknown")
        question_id = rule.get("question_id", "unknown")
        priority_tier = rule.get("priority_tier", "unknown")
        rule_kind = rule.get("rule_kind", "unknown")
        equivalence_class = rule.get("equivalence_class", "unknown")
        preferred_phase = rule.get("preferred_phase", "unknown")
        is_alert_setter = rule.get("is_alert_setter", False)
        info_gain = rule.get("info_gain", 0.0)
        grade_setter = rule.get("grade_setter", False)
        burden_cost = rule.get("burden_cost", 0.0)
        
        # Format thresholds for readability
        thresholds_text = ""
        if "thresholds" in rule and rule["thresholds"]:
            threshold_parts = []
            for threshold in rule["thresholds"]:
                if "emergency" in threshold and threshold["emergency"]:
                    threshold_parts.append("EMERGENCY")
                elif "min_severity" in threshold:
                    threshold_parts.append(f"Severity ≥ {threshold['min_severity']}")
                elif "op" in threshold and "value" in threshold:
                    threshold_parts.append(f"{threshold['op']} {threshold['value']}")
                elif "equals" in threshold:
                    threshold_parts.append(f"Equals: {threshold['equals']}")
            thresholds_text = " | ".join(threshold_parts)
        
        # Create the rule text
        rule_text = f"""TRIAGE RULE:
Symptom: {symptom}
Attribute: {attribute}
Question ID: {question_id}
Priority Tier: {priority_tier}
Rule Type: {rule_kind}
Equivalence Class: {equivalence_class}
Preferred Phase: {preferred_phase}
Alert Setter: {is_alert_setter}
Info Gain: {info_gain}
Grade Setter: {grade_setter}
Burden Cost: {burden_cost}
Thresholds: {thresholds_text}"""
        
        items.append(rule_text)
    
    print(f"[INGEST] Created {len(items)} triage rule chunks from {path}")
    
    # Process in smaller batches to avoid memory issues
    batch_size = 100
    total_vectors = 0
    
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        print(f"[INGEST] Processing triage KB batch {i//batch_size + 1}/{(len(items) + batch_size - 1)//batch_size} ({len(batch)} items)")
        
        # Create embeddings for this batch
        embs = embed_texts(batch)
        vectors = []
        
        for text, emb in zip(batch, embs):
            # Extract symptom name for metadata
            symptom_match = re.search(r"Symptom:\s*([^\n]+)", text)
            symptom = symptom_match.group(1).strip().lower() if symptom_match else "general"
            
            vid = stable_id("triage_kb", text[:200])
            vectors.append({
                "id": vid,
                "values": emb,
                "metadata": {
                    "type": "triage_kb",
                    "symptoms": [symptom],
                    "version": version,
                    "source": "triage_kb",
                    "text": text,
                }
            })
        
        # Upsert this batch
        index.upsert(vectors=vectors)
        total_vectors += len(vectors)
        print(f"[INGEST] Upserted triage KB batch: {len(vectors)} vectors")
    
    print(f"[INGEST] Total triage KB vectors ingested: {total_vectors}")


if __name__ == "__main__":
    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Go up to patient-api directory
    patient_api_dir = os.path.dirname(script_dir)
    
    # Run from repo root or adjust path
    ctcae_path = os.getenv("CTCAE_JSON", os.path.join(patient_api_dir, "model_inputs/rag/CTCAE.json"))
    questions_path = os.getenv("QUESTIONS_JSON", os.path.join(patient_api_dir, "model_inputs/rag/questions.json"))
    triage_kb_path = os.getenv("TRIAGE_KB_JSON", os.path.join(patient_api_dir, "model_inputs/rag/triage_kb_v2.json"))

    # ingest_ctcae(ctcae_path, version="CTCAE v5")
    # ingest_questions(questions_path)
    ingest_triage_kb(triage_kb_path, version="triage-rules.v2")
    print("[INGEST] Done.")