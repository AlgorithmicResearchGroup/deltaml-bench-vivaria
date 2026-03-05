#!/bin/bash
# This script patches the compiled server code to disable mp4-tasks cloning

cd /app/server

# Find and patch the server.js file
SERVER_FILE="/app/server/build/server/server.js"

if [ -f "$SERVER_FILE" ]; then
    echo "Patching $SERVER_FILE to disable mp4-tasks cloning..."
    # Remove the getOrCreateTaskRepo call from the Promise.all
    sed -i 's/, git\.getOrCreateTaskRepo(config4\.VIVARIA_DEFAULT_TASK_REPO_NAME)//' "$SERVER_FILE"
    echo "Patch applied successfully"
else
    echo "Error: $SERVER_FILE not found"
    exit 1
fi

# Now start the server normally
exec node --enable-source-maps build/index.js