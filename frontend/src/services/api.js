import { authService } from './auth';

let isRefreshing = false;
let refreshSubscribers = [];

function subscribeTokenRefresh(cb) {
  refreshSubscribers.push(cb);
}

function onRefreshed(token) {
  refreshSubscribers.forEach((cb) => cb(token));
  refreshSubscribers = [];
}

export async function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = localStorage.getItem('access_token');
  
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  
  options.headers = headers;

  try {
    const response = await fetch(url, options);

    if (response.status === 401) {
      // Access token hết hạn, thực hiện refresh
      if (!isRefreshing) {
        isRefreshing = true;
        try {
          const newTokens = await authService.refreshToken();
          isRefreshing = false;
          onRefreshed(newTokens.access_token);
        } catch (refreshErr) {
          isRefreshing = false;
          authService.logout();
          window.location.href = '/login';
          throw new Error('Session expired');
        }
      }

      // Đợi refresh token xong rồi thực hiện lại request cũ
      return new Promise((resolve) => {
        subscribeTokenRefresh((newToken) => {
          headers.set('Authorization', `Bearer ${newToken}`);
          options.headers = headers;
          resolve(fetch(url, options));
        });
      });
    }

    return response;
  } catch (error) {
    throw error;
  }
}
