import { useParams, Navigate } from 'react-router-dom';
import RPStoryThread from '@/features/storylab/RPStoryThread';

export default function RPStoryPage() {
  const { threadId } = useParams<{ threadId: string }>();
  const id = Number(threadId);
  if (!threadId || isNaN(id)) return <Navigate to="/rp-stories" replace />;
  return <RPStoryThread threadId={id} />;
}
