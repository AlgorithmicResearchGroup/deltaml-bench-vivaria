#!/bin/bash

echo "Patching Auth0 in UI JavaScript files..."

# Find and patch the ErrorBoundary file
ERROR_FILE="/srv/assets/ErrorBoundary-DQH0sisk.js"

if [ -f "$ERROR_FILE" ]; then
    echo "Found ErrorBoundary file, patching Auth0 errors..."

    # Create a backup
    cp "$ERROR_FILE" "$ERROR_FILE.bak"

    # Replace the error throwing with a console log and early return
    # This handles the secure origin check
    sed -i 's/throw new Error("\s*auth0-spa-js must run on a secure origin[^"]*")/console.log("Auth0 secure origin check bypassed");return {isAuthenticated:async()=>false,loginWithRedirect:async()=>{},logout:()=>{},getUser:async()=>null,getIdTokenClaims:async()=>null,getTokenSilently:async()=>"",getAccessTokenSilently:async()=>"",handleRedirectCallback:async()=>({}),checkSession:async()=>{}}/g' "$ERROR_FILE"

    # Also patch any w$2().subtle check to always return a mock
    sed -i 's/void 0 === w\$2()\.subtle/false/g' "$ERROR_FILE"

    # Replace Auth0Client constructor references
    sed -i 's/new Auth0Client(/new MockAuth0Client(/g' "$ERROR_FILE"

    # Check if createAuth0Client is called and replace it
    sed -i 's/createAuth0Client(/mockCreateAuth0Client(/g' "$ERROR_FILE"

    echo "Patching complete!"
else
    echo "ErrorBoundary file not found!"
fi

# Also patch the main JS file
MAIN_FILE="/srv/assets/main-BWCS6WSG.js"
if [ -f "$MAIN_FILE" ]; then
    echo "Patching main.js file..."
    cp "$MAIN_FILE" "$MAIN_FILE.bak"

    # Replace Auth0 related code
    sed -i 's/createAuth0Client(/mockCreateAuth0Client(/g' "$MAIN_FILE"
    sed -i 's/new Auth0Client(/new MockAuth0Client(/g' "$MAIN_FILE"

    echo "Main.js patched!"
fi

echo "All patches applied!"