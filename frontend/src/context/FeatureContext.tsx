import { createContext, useContext, useEffect, useState } from 'react';
import { api } from '../api/client';
import { useAuth } from './AuthContext';

interface FeatureFlags {
  [key: string]: boolean;
}

interface FeatureReasons {
  [key: string]: string;
}

interface FeatureMessages {
  [key: string]: string;
}

interface FeatureContextType {
  features: FeatureFlags;
  reasons: FeatureReasons;
  messages: FeatureMessages;
  loading: boolean;
  unavailable: boolean;
  isEnabled: (key: string) => boolean;
  isKnown: (key: string) => boolean;
  reasonFor: (key: string) => string;
  messageFor: (key: string) => string;
  refresh: () => Promise<void>;
}

const FeatureContext = createContext<FeatureContextType>({
  features: {},
  reasons: {},
  messages: {},
  loading: true,
  unavailable: false,
  isEnabled: () => true,
  isKnown: () => false,
  reasonFor: () => '',
  messageFor: () => '',
  refresh: () => Promise.resolve(),
});

export function FeatureProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const [features, setFeatures] = useState<FeatureFlags>({});
  const [reasons, setReasons] = useState<FeatureReasons>({});
  const [messages, setMessages] = useState<FeatureMessages>({});
  const [loading, setLoading] = useState(true);
  const [unavailable, setUnavailable] = useState(false);

  interface FeaturesResponse {
  features?: FeatureFlags;
  reasons?: FeatureReasons;
  messages?: FeatureMessages;
}

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
      const data = await api.get('/auth/features/') as FeaturesResponse;
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

  function isEnabled(key: string) {
    if (loading) return false; // hide optional modules until flags load
    if (!(key in features)) return false;
    return !!features[key];
  }

  // Whether the flag is genuinely off, as opposed to unknown because the
  // request failed. Callers must not claim a feature was disabled when the
  // truth is that we could not ask.
  function isKnown(key: string) {
    return !loading && !unavailable && key in features;
  }

  function reasonFor(key: string) {
    return reasons?.[key] || '';
  }

  // The explanation the API already wrote for this key, verbatim. Keeping the
  // sentence server-side is the point: this component used to build its own
  // copy of it, and the two drifted into saying different things about the
  // same 403.
  function messageFor(key: string) {
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

export function useFeatures(): FeatureContextType {
  return useContext(FeatureContext);
}