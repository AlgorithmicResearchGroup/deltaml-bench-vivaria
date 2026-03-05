import os
import sys
import warnings
import logging
import datetime
import asyncio
import sqlite3
import json
from typing import List, Dict, Any, Optional
from pathlib import Path
from contextlib import contextmanager
import threading

warnings.filterwarnings("ignore")
logging.getLogger("sqlalchemy").setLevel(logging.ERROR)

# Thread-local storage for SQLite connections
_thread_local = threading.local()

class AgentConversation:
    """Simple conversation class for SQLite storage"""
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.run_id = kwargs.get('run_id', '')
        self.tool = kwargs.get('tool', '')
        self.status = kwargs.get('status', '')
        self.attempt = kwargs.get('attempt', '')
        self.stdout = kwargs.get('stdout', '')
        self.stderr = kwargs.get('stderr', '')
        self.total_tokens = kwargs.get('total_tokens', 0)
        self.prompt_tokens = kwargs.get('prompt_tokens', 0)
        self.response_tokens = kwargs.get('response_tokens', 0)
        self.created_at = kwargs.get('created_at', datetime.datetime.utcnow())
        self.updated_at = kwargs.get('updated_at', datetime.datetime.utcnow())
        self.user_id = kwargs.get('user_id')
        self.embedding = kwargs.get('embedding', '')


class AsyncAgentMemory:
    def __init__(self):
        # Create data directory
        if hasattr(sys, '_MEIPASS'):
            # Running from PyInstaller bundle
            self.data_dir = Path(sys._MEIPASS).parent / 'data'
        else:
            # Running from source
            self.data_dir = Path("/tmp/prospectml_data")
        
        self.data_dir.mkdir(exist_ok=True)
        self.db_path = self.data_dir / "agent_memory.db"
        
        # Initialize database
        self._init_database()
        
        # Disable embeddings for now (can be re-enabled later)
        self._encoder = None
        self._encoder_lock = asyncio.Lock()
        self.use_embeddings = False

    def _get_connection(self):
        """Get thread-local SQLite connection"""
        if not hasattr(_thread_local, 'connection'):
            _thread_local.connection = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False
            )
            _thread_local.connection.row_factory = sqlite3.Row
        return _thread_local.connection

    def _init_database(self):
        """Initialize SQLite database schema"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS agent_memory_4 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                tool TEXT,
                status TEXT,
                attempt TEXT,
                stdout TEXT,
                stderr TEXT,
                total_tokens INTEGER,
                prompt_tokens INTEGER,
                response_tokens INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_id INTEGER,
                embedding TEXT
            )
        ''')
        
        # Create indices for better performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_run_id ON agent_memory_4(run_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_id ON agent_memory_4(user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON agent_memory_4(created_at)')
        
        conn.commit()

    async def get_encoder(self):
        """Lazy loading of encoder (disabled for SQLite version)"""
        return None

    async def encode_text_async(self, text: str) -> List[float]:
        """Async text encoding (returns empty list for SQLite version)"""
        return []

    async def save_conversation_memory(
        self,
        user_id: int,
        run_id: str,
        previous_subtask_tool: str,
        previous_subtask_result: str,
        previous_subtask_attempt: str,
        previous_subtask_output: str,
        previous_subtask_errors: str,
        total_tokens: int,
        prompt_tokens: int,
        response_tokens: int,
    ) -> None:
        """Save conversation memory to SQLite"""
        logging.info(f"save_conversation_memory called - run_id: {run_id}, tool: {previous_subtask_tool}")
        try:
            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._save_conversation_sync,
                user_id, run_id, previous_subtask_tool, previous_subtask_result,
                previous_subtask_attempt, previous_subtask_output, previous_subtask_errors,
                total_tokens, prompt_tokens, response_tokens
            )
            logging.info(f"Successfully saved to database: {self.db_path}")
        except Exception as e:
            logging.error(f"Error saving conversation memory: {e}")
            logging.error(f"Database path: {self.db_path}")
            import traceback
            logging.error(traceback.format_exc())
            # Don't raise - memory is optional

    def _save_conversation_sync(
        self, user_id, run_id, tool, status, attempt, stdout, stderr,
        total_tokens, prompt_tokens, response_tokens
    ):
        """Synchronous save to SQLite"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO agent_memory_4 
            (user_id, run_id, tool, status, attempt, stdout, stderr, 
             total_tokens, prompt_tokens, response_tokens, embedding)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id, run_id, str(tool), str(status), str(attempt),
            str(stdout)[:10000],  # Limit stdout size
            str(stderr)[:10000],  # Limit stderr size
            total_tokens, prompt_tokens, response_tokens,
            ''  # Empty embedding for now
        ))
        
        conn.commit()

    async def get_conversation_memory(self, run_id: str) -> str:
        """Get conversation memory from SQLite"""
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._get_conversation_sync,
                run_id
            )
            return result
        except Exception as e:
            logging.error(f"Error getting conversation memory: {e}")
            return ""

    def _get_conversation_sync(self, run_id: str) -> str:
        """Synchronous get from SQLite"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM agent_memory_4 
            WHERE run_id = ? 
            ORDER BY created_at DESC 
            LIMIT 100
        ''', (run_id,))
        
        rows = cursor.fetchall()
        
        memories = []
        for row in reversed(rows):
            memories.append({
                "tool": row['tool'],
                "status": row['status'],
                "attempt": row['attempt'],
                "stdout": row['stdout'],
                "stderr": row['stderr'],
                "total_tokens": row['total_tokens'],
                "prompt_tokens": row['prompt_tokens'],
                "response_tokens": row['response_tokens'],
            })
        
        # Format memory output
        full_output_mems = "Short-term Memory (Last 100 steps)\n" + "-" * 100 + "\n"
        for idx, item in enumerate(memories):
            formatted_string = "\n".join(
                [f"{key}: {value}" for key, value in item.items()]
            )
            full_output_mems += (
                f"Step {idx + 1}\n{formatted_string}\n" + "-" * 100 + "\n"
            )
        
        return full_output_mems

    async def get_error_specific_memory(self, user_id: int, error_type: str, error_text: str, limit: int = 5) -> str:
        """Get error-specific memory (simplified for SQLite)"""
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._get_error_memory_sync,
                user_id, error_type, error_text, limit
            )
            return result
        except Exception as e:
            logging.error(f"Error getting error-specific memory: {e}")
            return ""

    def _get_error_memory_sync(self, user_id: int, error_type: str, error_text: str, limit: int) -> str:
        """Synchronous error memory retrieval"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Simple text search for similar errors
        cursor.execute('''
            SELECT * FROM agent_memory_4 
            WHERE user_id = ? 
            AND status = 'failure'
            AND stderr IS NOT NULL
            AND stderr LIKE ?
            ORDER BY created_at DESC 
            LIMIT ?
        ''', (user_id, f'%{error_type}%', limit))
        
        rows = cursor.fetchall()
        
        if not rows:
            return ""
        
        context_parts = [f"\n🚨 SIMILAR ERROR PATTERNS FOUND ({len(rows)} matches):\n"]
        
        for row in rows:
            context_parts.append(f"""
Tool: {row['tool']}
Error: {row['stderr'][:500]}...
Attempt: {row['attempt']}
---""")
        
        return "\n".join(context_parts)

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity (kept for compatibility)"""
        if not vec1 or not vec2:
            return 0.0
        
        import math
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        magnitude1 = math.sqrt(sum(a * a for a in vec1))
        magnitude2 = math.sqrt(sum(b * b for b in vec2))
        
        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0
        
        return dot_product / (magnitude1 * magnitude2)

    async def close(self):
        """Close database connections"""
        # SQLite connections are thread-local and will be cleaned up automatically
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def get_current_run_memory(self, run_id: str, limit: int = 10) -> str:
        """Get recent attempts from the CURRENT run"""
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._get_current_run_memory_sync,
                run_id, limit
            )
            return result
        except Exception as e:
            logging.error(f"Error getting current run memory: {e}")
            return "Could not retrieve recent memory."

    def _get_current_run_memory_sync(self, run_id: str, limit: int) -> str:
        """Synchronous get current run memory"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM agent_memory_4 
            WHERE run_id = ? 
            ORDER BY created_at DESC 
            LIMIT ?
        ''', (run_id, limit))
        
        rows = cursor.fetchall()
        
        if not rows:
            return "No previous attempts in this run."

        memory_parts = [f"\n📋 RECENT ATTEMPTS IN THIS RUN (Last {len(rows)}):\n"]
        
        for idx, row in enumerate(reversed(rows)):
            attempt_num = idx + 1
            status_icon = "✅" if row['status'] == "success" else "❌"
            
            memory_parts.append(f"\n{status_icon} ATTEMPT #{attempt_num}:")
            memory_parts.append(f"   Action: {row['tool']}")
            memory_parts.append(f"   What was tried: {row['attempt']}")
            
            if row['stderr']:
                memory_parts.append(f"   ❌ ERROR: {row['stderr']}")
            
            if row['stdout']:
                memory_parts.append(f"   📤 Output: {row['stdout'][:200]}...")
            
            memory_parts.append(f"   Status: {row['status']}")
            memory_parts.append("-" * 80)

        # Add pattern detection
        failure_patterns = self._detect_failure_patterns(list(reversed(rows)))
        if failure_patterns:
            memory_parts.append(f"\n🔍 DETECTED PATTERNS:")
            for pattern in failure_patterns:
                memory_parts.append(f"   ⚠️ {pattern}")

        return "\n".join(memory_parts)

    def _detect_failure_patterns(self, rows: List) -> List[str]:
        """Detect if the agent is repeating the same failures"""
        patterns = []
        
        # Group by error type
        error_counts = {}
        recent_errors = []
        
        for row in rows:
            if row['status'] == "failure" and row['stderr']:
                error_text = row['stderr'].lower()
                
                # Simple error classification
                if "filenotfounderror" in error_text:
                    error_type = "FileNotFoundError"
                elif "importerror" in error_text or "modulenotfounderror" in error_text:
                    error_type = "ImportError"
                elif "nameerror" in error_text:
                    error_type = "NameError"
                else:
                    error_type = "Other"
                
                error_counts[error_type] = error_counts.get(error_type, 0) + 1
                recent_errors.append((error_type, row['stderr'][:100]))
        
        # Detect repetitive patterns
        for error_type, count in error_counts.items():
            if count >= 3:
                patterns.append(f"REPEATED {error_type} ({count} times) - Need different approach!")
            elif count >= 2:
                patterns.append(f"Multiple {error_type} failures ({count} times) - Consider alternative")
        
        return patterns

    async def get_simple_context(self, run_id: str, current_error: str = None) -> str:
        """Get simple, focused context for the current situation"""
        # Get recent run history
        run_context = await self.get_current_run_memory(run_id, limit=8)
        
        context_parts = [run_context]
        
        # If there's a current error, add specific guidance
        if current_error:
            error_guidance = self._get_error_guidance(current_error)
            if error_guidance:
                context_parts.append(f"\n🎯 SPECIFIC GUIDANCE FOR CURRENT ERROR:\n{error_guidance}")
        
        return "\n".join(context_parts)

    def _get_error_guidance(self, error_text: str) -> str:
        """Simple, direct guidance for common errors"""
        error_lower = error_text.lower()
        
        if "filenotfounderror" in error_lower or "no such file" in error_lower:
            return """
❌ FILE NOT FOUND - IMMEDIATE ACTIONS:
1. List current directory: print(os.listdir('.'))
2. Check what files actually exist before using them
3. Look for dataset download instructions
4. Use absolute paths or verify relative paths
5. Create missing directories if needed

🚫 STOP assuming file paths exist - VERIFY first!
"""
        elif "importerror" in error_lower or "modulenotfounderror" in error_lower:
            return """
❌ IMPORT ERROR - IMMEDIATE ACTIONS:
1. Try: pip install [missing_package]
2. Check spelling of import names
3. Use only built-in libraries if installation fails
4. Import from different locations

🚫 STOP assuming packages are installed!
"""
        elif "nameerror" in error_lower:
            return """
❌ NAME ERROR - IMMEDIATE ACTIONS:
1. Check variable spelling and case
2. Ensure variables are defined before use
3. Check function/variable scope
4. Initialize all variables properly

🚫 STOP using undefined variables!
"""
        else:
            return "Review the error carefully and try a different approach."

    async def save_simple_attempt(
        self,
        run_id: str,
        user_id: int,
        action: str,
        what_was_tried: str,
        result_status: str,
        output: str = "",
        error: str = "",
    ) -> None:
        """Save a simple attempt record"""
        await self.save_conversation_memory(
            user_id=user_id,
            run_id=run_id,
            previous_subtask_tool=action,
            previous_subtask_result=result_status,
            previous_subtask_attempt=what_was_tried,
            previous_subtask_output=output,
            previous_subtask_errors=error,
            total_tokens=0,
            prompt_tokens=0,
            response_tokens=0,
        )

    async def get_context_for_llm(self, run_id: str = None) -> str:
        """Get context for LLM - combines recent memory with any current error context"""
        if run_id:
            return await self.get_simple_context(run_id)
        else:
            return "No context available - run_id not provided."

    async def add_to_conversation(self, role: str, content: str) -> None:
        """Add a conversation entry - placeholder for compatibility"""
        logging.info(f"Conversation [{role}]: {content[:100]}...")
        # In a real implementation, this might save to the database
        pass