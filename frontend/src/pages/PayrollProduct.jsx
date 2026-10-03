import useMarketingPage from '../hooks/useMarketingPage';
import { MarketingSections } from '../components/MarketingSections';

// Copy, section order and links are managed in /platform-admin → Marketing
// content. See the note in Platform.jsx about the fallback behaviour.
export default function PayrollProduct() {
  const content = useMarketingPage('payroll-product');
  return <MarketingSections content={content} />;
}
