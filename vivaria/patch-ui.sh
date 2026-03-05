#!/bin/bash
# Patch script to disable Auth0 in the UI by modifying the compiled JS

echo "Patching UI to disable Auth0..."

# Find the ErrorBoundary JS file that contains Auth0 initialization
ERROR_FILE="/srv/assets/ErrorBoundary-DQH0sisk.js"

if [ -f "$ERROR_FILE" ]; then
    echo "Patching $ERROR_FILE to bypass Auth0 secure origin check..."

    # Replace the error throwing with a console log
    # This is a bit hacky but should work
    sed -i 's/throw new Error.*auth0-spa-js must run on a secure origin/console.log("Auth0 check bypassed");return;\/\//' "$ERROR_FILE"

    # Also try to replace any Auth0Client constructor calls
    sed -i 's/new Auth0Client/new MockAuth0Client/g' "$ERROR_FILE"

    echo "Patch applied to ErrorBoundary JS"
fi

# Start Caddy normally
exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile