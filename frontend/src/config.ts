export const config = {
  // En desarrollo usa '/api' (Vite proxy). En prod usa VITE_API_URL si existe, si no fallback a '/api'
  API_BASE_URL: import.meta.env.VITE_API_URL || '/api'
};
