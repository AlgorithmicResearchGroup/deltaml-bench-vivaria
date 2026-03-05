"""Write agent state directly to database"""
import os
import json
import time
import threading
import requests
from pathlib import Path


class DatabaseStateWriter:
    """Write agent state to database via web API"""
    
    def __init__(self, run_id):
        self.run_id = run_id
        self.running = False
        self.thread = None
        self.web_url = os.environ.get('WEB_SERVICE_URL', 'http://prospectml:5000')
        self.last_state = None
        
    def start(self):
        """Start the state writer thread"""
        self.running = True
        self.thread = threading.Thread(target=self._write_loop, daemon=True)
        self.thread.start()
        print(f"[DatabaseStateWriter] Started for run {self.run_id}")
    
    def stop(self):
        """Stop the state writer thread"""
        self.running = False
        if self.thread:
            self.thread.join()
        print(f"[DatabaseStateWriter] Stopped for run {self.run_id}")
    
    def _write_loop(self):
        """Main loop to write state periodically"""
        while self.running:
            try:
                # Read local state file
                state_file = Path("/tmp/tree_monitor_state.json")
                if state_file.exists():
                    with open(state_file) as f:
                        state_data = f.read()
                    
                    # Only send if state has changed
                    if state_data != self.last_state:
                        # Send to web API
                        url = f"{self.web_url}/api/agent-state/{self.run_id}"
                        response = requests.post(
                            url,
                            data=state_data,
                            headers={"Content-Type": "application/json"},
                            timeout=5
                        )
                        
                        if response.status_code == 200:
                            self.last_state = state_data
                            print(f"[DatabaseStateWriter] State updated for run {self.run_id}")
                        else:
                            print(f"[DatabaseStateWriter] Failed to update state: {response.status_code}")
                            
            except Exception as e:
                print(f"[DatabaseStateWriter] Error: {e}")
            
            # Wait before next update
            time.sleep(5)


# Global instance management
_writer_instance = None


def start_db_state_writer(run_id):
    """Start the database state writer"""
    global _writer_instance
    if _writer_instance is None:
        _writer_instance = DatabaseStateWriter(run_id)
        _writer_instance.start()
    return _writer_instance


def stop_db_state_writer():
    """Stop the database state writer"""
    global _writer_instance
    if _writer_instance:
        _writer_instance.stop()
        _writer_instance = None