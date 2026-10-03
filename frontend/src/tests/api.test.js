import { api } from '../api/client';
import { vi, describe, beforeEach, it, expect } from 'vitest';

// Mock fetch globally
global.fetch = vi.fn();

describe('API client', () => {
  beforeEach(() => {
    fetch.mockClear();
  });

  it('makes GET requests with correct URL', async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      text: () => Promise.resolve(JSON.stringify({ data: 'test' })),
    });

    const result = await api.get('/test/');
    expect(result).toEqual({ data: 'test' });
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/test/'),
      expect.objectContaining({ method: 'GET' })
    );
  });

  it('makes POST requests with JSON body', async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      text: () => Promise.resolve(JSON.stringify({ success: true })),
    });

    await api.post('/test/', { key: 'value' });
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/test/'),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ key: 'value' }),
      })
    );
  });

  it('includes CSRF token for non-GET requests', async () => {
    // Mock document.cookie
    Object.defineProperty(document, 'cookie', {
      value: 'csrftoken=test-csrf-token',
      writable: true,
    });

    fetch.mockResolvedValueOnce({
      ok: true,
      text: () => Promise.resolve(JSON.stringify({ success: true })),
    });

    await api.post('/test/', { key: 'value' });
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/test/'),
      expect.objectContaining({
        headers: expect.objectContaining({
          'X-CSRFToken': 'test-csrf-token',
        }),
      })
    );
  });

  it('throws error on non-ok response', async () => {
    fetch.mockResolvedValueOnce({
      ok: false,
      status: 400,
      text: () => Promise.resolve(JSON.stringify({ detail: 'Bad request' })),
    });

    await expect(api.get('/test/')).rejects.toThrow('Bad request');
  });

  it('handles network errors', async () => {
    fetch.mockRejectedValueOnce(new Error('Failed to fetch'));

    await expect(api.get('/test/')).rejects.toThrow(
      'Cannot reach the API server. Check that the backend is running and VITE_API_URL is correct.'
    );
  });

  it('handles FormData without Content-Type', async () => {
    const formData = new FormData();
    formData.append('file', new File(['test'], 'test.txt'));

    fetch.mockResolvedValueOnce({
      ok: true,
      text: () => Promise.resolve(JSON.stringify({ uploaded: true })),
    });

    await api.upload('/upload/', formData);
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/upload/'),
      expect.objectContaining({
        method: 'POST',
        body: formData,
      })
    );
  });
});