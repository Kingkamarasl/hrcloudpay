import { useEffect, useState } from 'react';
import { api } from '../api/client';

interface MarketingPage {
  slug: string;
  content: Record<string, unknown>;
}

// Loads a managed marketing page for a public landing page.
//
// The failure behaviour is the important part. A public page must never depend
// on an admin feature being up: the content endpoint is a public URL, it is one
// more thing that can fail, and a visitor cannot act on an error. So a failure
// resolves to `null` and the page falls back to the copy shipped in its JSX,
// which is why every caller keeps a `DEFAULT_*` constant. The homepage already
// swallowed this failure; it is now the rule rather than a habit.
export default function useMarketingPage(slug: string): Record<string, unknown> | null {
  const [content, setContent] = useState<Record<string, unknown> | null>(null);
  useEffect(() => {
    let current = true;
    api.get<MarketingPage>(`/auth/marketing-pages/${slug}/`)
      .then((page) => { if (current) setContent(page?.content || null); })
      .catch(() => { if (current) setContent(null); });
    return () => { current = false; };
  }, [slug]);
  return content;
}