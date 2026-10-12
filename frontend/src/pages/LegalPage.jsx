import useMarketingPage from '../hooks/useMarketingPage';
import {MarketingSections} from '../components/MarketingSections';

// One component for all three legal pages. The copy lives in the database as
// `prose_blocks`, so a platform admin edits it from Marketing without a deploy
// - which matters more here than anywhere else, because these change when the
// law does, when a country rule is added, or when the AI provider changes.
//
// The slug is passed as a prop rather than read from useParams. A shared
// `/legal/:slug` route would swallow any unmatched top-level path and show a
// legal page instead of a 404, which is the failure mode a catch-all route on a
// marketing site is not worth. Three explicit routes, one component: adding a
// fourth legal page is a route and a migration row, not a new component.
export default function LegalPage({slug}) {
  const content = useMarketingPage(slug);
  return <MarketingSections content={content} />;
}