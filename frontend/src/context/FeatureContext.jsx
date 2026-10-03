import { createContext, useContext, useEffect, useState } from 'react';
import { api } from '../api/client';
import { useAuth } from './AuthContext';

const FeatureContext = createContext({
  features: {}, reasons: {}, messages: {}, loading: true, unavailable: false,
  isEnabled: () => true, isKnown: () => false,
  reasonFor: () => '', messageFor: () => '', refresh: () => {},
});

export function FeatureProvider({ children }) {
  const { user } = useAuth();
  const [features, setFeatures] = useState({});
  const [reasons, setReasons] = useState({});
  const [messages, setMessages] = useState({});
  const [loading, setLoading] = useState(true);
  const [unavailable, setUnavailable] = useState(false);

  async function refresh() {
    if (!user) {
      setFeatures({});
      setReasons({});
      setMessages({});
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const data = await api.get('/auth/features/');
      setFeatures(data?.features || {});
      setReasons(data?.reasons || {});
      setMessages(data?.messages || {});
      setUnavailable(false);
    } catch {
      // A failed flags request is NOT the same as "everything is disabled".
      // Treating it as one made a network blip look like an administrator had
      // switched off the whole product, and the UI said so in those words.
      setFeatures({});
      setReasons({});
      setMessages({});
      setUnavailable(true);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, [user?.id]);

  function isEnabled(key) {
    if (loading) return false; // hide optional modules until flags load
    if (!(key in features)) return false;
    return !!features[key];
  }

  // Whether the flag is genuinely off, as opposed to unknown because the
  // request failed. Callers must not claim a feature was disabled when the
  // truth is that we could not ask.
  function isKnown(key) {
    return !loading && !unavailable && key in features;
  }

  function reasonFor(key) {
    return reasons?.[key] || '';
  }

  // The explanation the API already wrote for this key, verbatim. Keeping the
  // sentence server-side is the point: this component used to build its own
  // copy of it, and the two drifted into saying different things about the
  // same 403.
  function messageFor(key) {
    return messages?.[key] || '';
  }

  return (
    <FeatureContext.Provider
      value={{ features, reasons, messages, loading, unavailable, isEnabled, isKnown, reasonFor, messageFor, refresh }}
    >
      {children}
    </FeatureContext.Provider>
  );
}

export function useFeatures() {
  return useContext(FeatureContext);
}
