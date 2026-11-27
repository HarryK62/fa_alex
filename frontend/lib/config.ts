// The backend API always runs on this machine (scripts/start_local.py starts it on port 8000)
export const getApiUrl = () => process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export const API_URL = getApiUrl();

// Prices are stored in the backend's BASE_CURRENCY (AUD by default)
export const MONEY = process.env.NEXT_PUBLIC_MONEY_PREFIX || 'AUD$';
