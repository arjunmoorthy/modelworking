#!/usr/bin/env python3
"""
Script to clear RAG cache in Redis after adding new documents
"""

import os
import redis
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def clear_rag_cache():
    """Clear all RAG-related cache entries from Redis."""
    redis_url = os.getenv("REDIS_URL")
    
    if not redis_url:
        print("❌ REDIS_URL not found in environment variables")
        return False
    
    try:
        # Connect to Redis
        r = redis.from_url(redis_url)
        r.ping()  # Test connection
        print("✅ Connected to Redis")
        
        # Find all RAG-related keys
        rag_keys = r.keys("rag:*")
        
        if not rag_keys:
            print("ℹ️  No RAG cache keys found")
            return True
        
        print(f"🔍 Found {len(rag_keys)} RAG cache keys")
        
        # Clear all RAG keys
        deleted_count = 0
        for key in rag_keys:
            r.delete(key)
            deleted_count += 1
        
        print(f"🗑️  Cleared {deleted_count} RAG cache keys")
        
        # Verify cache is cleared
        remaining_keys = r.keys("rag:*")
        if not remaining_keys:
            print("✅ All RAG cache successfully cleared")
        else:
            print(f"⚠️  {len(remaining_keys)} RAG keys still remain")
        
        return True
        
    except redis.ConnectionError:
        print("❌ Could not connect to Redis")
        return False
    except Exception as e:
        print(f"❌ Error clearing cache: {e}")
        return False

if __name__ == "__main__":
    print("🧹 Clearing RAG cache...")
    print()
    
    success = clear_rag_cache()
    
    if success:
        print("\n🎉 Cache cleared successfully!")
        print("Next time you chat, fresh RAG results will be retrieved from Pinecone.")
    else:
        print("\n❌ Failed to clear cache. Check Redis connection.")
