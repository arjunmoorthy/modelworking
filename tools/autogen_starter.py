import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

import autogen


def read_text_file(file_path: Path) -> str:
    if not file_path.exists():
        raise FileNotFoundError(f"Missing required file: {file_path}")
    return file_path.read_text(encoding="utf-8").strip()


def build_llm_config(model: str) -> Dict:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is required for AutoGen. Set it in your environment."
        )
    return {
        "config_list": [
            {
                "model": model,
                "api_key": api_key,
            }
        ],
        "timeout": 120,
        "temperature": 0.2,
    }


def load_agent_system_messages(context_dir: Path) -> Dict[str, str]:
    files = {
        "orchestrator": context_dir / "agent1_orchestrator",
        "triage_agent": context_dir / "agent2_triage_agent",
        "info_gain": context_dir / "agent3_info_gain",
        "response_writer": context_dir / "agent4_response_writer",
        "summary": context_dir / "agent5_summary",
    }
    return {name: read_text_file(path) for name, path in files.items()}


def run_group_chat(
    output_path: Path,
    model: str = "gpt-4o",
    task: Optional[str] = None,
) -> str:
    # Resolve context files relative to this script
    patient_api_dir = Path(__file__).resolve().parents[1]
    context_dir = patient_api_dir / "model_inputs" / "context"

    system_messages = load_agent_system_messages(context_dir)

    llm_config = build_llm_config(model)

    # Define agents
    orchestrator = autogen.AssistantAgent(
        name="orchestrator",
        system_message=system_messages["orchestrator"],
        llm_config=llm_config,
    )
    triage = autogen.AssistantAgent(
        name="triage_agent",
        system_message=system_messages["triage_agent"],
        llm_config=llm_config,
    )
    info_gain = autogen.AssistantAgent(
        name="info_gain",
        system_message=system_messages["info_gain"],
        llm_config=llm_config,
    )
    response_writer = autogen.AssistantAgent(
        name="response_writer",
        system_message=system_messages["response_writer"],
        llm_config=llm_config,
    )
    summary = autogen.AssistantAgent(
        name="summary",
        system_message=system_messages["summary"],
        llm_config=llm_config,
    )

    user = autogen.UserProxyAgent(
        name="task_caller",
        human_input_mode="NEVER",
        code_execution_config=False,
    )

    groupchat = autogen.GroupChat(
        agents=[orchestrator, triage, info_gain, response_writer, summary],
        messages=[],
        max_round=8,
        speaker_selection_method="auto",
    )
    manager = autogen.GroupChatManager(groupchat=groupchat, llm_config=llm_config)

    default_task = (
        "Collaborate to draft a concise starter markdown document for the OncoLife triage chatbot. "
        "Follow your role instructions strictly. "
        "Include: 1) a high-level triage flow outline; 2) example short-phase and long-phase question stems; "
        "3) disposition mapping overview; 4) response style guide; 5) a closing summary section. "
        "Keep it under 800 words and use clear markdown headings."
    )

    starter_task = task or default_task
    user.initiate_chat(manager, message=starter_task)

    # Find the final message from the summary agent, else fall back to the last message
    final_text: Optional[str] = None
    for m in reversed(groupchat.messages):
        if isinstance(m, dict) and m.get("name") == summary.name:
            final_text = m.get("content")
            break
    if not final_text and groupchat.messages:
        last = groupchat.messages[-1]
        if isinstance(last, dict):
            final_text = last.get("content")

    final_text = final_text or "(No content generated.)"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(final_text, encoding="utf-8")
    return final_text


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Generate starter markdown via AutoGen group chat.")
    parser.add_argument(
        "--model",
        default="gpt-4o",
        help="LLM model name (default: gpt-4o)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output markdown path. Defaults to model_inputs/context/starter_document.md",
    )
    parser.add_argument(
        "--task",
        default=None,
        help="Override the default task prompt for the group chat.",
    )

    args = parser.parse_args(argv)

    # Compute default output path if not given
    if args.out is None:
        patient_api_dir = Path(__file__).resolve().parents[1]
        args.out = str(patient_api_dir / "model_inputs" / "context" / "starter_document.md")

    output_path = Path(args.out)
    try:
        text = run_group_chat(output_path=output_path, model=args.model, task=args.task)
        print(f"Wrote starter document to: {output_path}")
        # Print a short preview
        preview = text[:200].replace("\n", " ")
        print(f"Preview: {preview}...")
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


