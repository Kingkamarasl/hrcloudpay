import useMarketingPage from '../hooks/useMarketingPage';
import { MarketingSections } from '../components/MarketingSections';

// Copy, section order and links are managed in /platform-admin → Marketing
// content. If that endpoint is unavailable `useMarketingPage` resolves to null
// and this page renders nothing, because there is no shipped copy to fall back
// to any more - the copy now lives in the database. That is a deliberate
// trade: the platform admin is the single source of truth for these pages.
export default function Platform() {
  const content = useMarketingPage('platform');
  return <MarketingSections content={content} />;
}
