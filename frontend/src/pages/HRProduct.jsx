import useMarketingPage from '../hooks/useMarketingPage';
import { MarketingSections } from '../components/MarketingSections';

// Copy, section order and links are managed in /platform-admin → Marketing
// content. See the note in Platform.jsx about the fallback behaviour.
export default function HRProduct() {
  const content = useMarketingPage('hr');
  return <MarketingSections content={content} />;
}
