// Patch to disable Auth0 in the UI
// This script modifies window objects to prevent Auth0 initialization

// Override the Auth0 client creation to return a mock
window.createAuth0Client = async function() {
  console.log('Auth0 disabled - using mock client');
  return {
    isAuthenticated: async () => false,
    loginWithRedirect: async () => {
      console.log('Auth0 login disabled');
      window.location.href = '/';
    },
    logout: () => console.log('Auth0 logout disabled'),
    getUser: async () => null,
    getIdTokenClaims: async () => null,
    getTokenSilently: async () => null,
    handleRedirectCallback: async () => ({})
  };
};

// Also patch any global Auth0 references
if (window.Auth0Client) {
  window.Auth0Client = function() {
    return window.createAuth0Client();
  };
}

console.log('Auth0 patch applied - authentication disabled');