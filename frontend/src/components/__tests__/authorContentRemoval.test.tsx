// @vitest-environment jsdom
/**
 * W-07A — an author can always remove what they published.
 *
 * The two shared controls every surface reuses:
 *   * PostMenu — the post delete, whose confirmation must say truthfully what
 *     a hard delete takes with it (reactions and comments cascade);
 *   * CommentSection — an author-only Delete on each of the viewer's own
 *     comments, confirmed through the shared ConfirmDialog.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Comment } from '@/lib/types';

const deletePost = vi.fn();
const deleteComment = vi.fn();
const getPostComments = vi.fn();

vi.mock('@/lib/apiClient', () => ({
  apiClient: {
    deletePost: (...a: unknown[]) => deletePost(...a),
    deleteComment: (...a: unknown[]) => deleteComment(...a),
    getPostComments: (...a: unknown[]) => getPostComments(...a),
    createComment: vi.fn(),
    hasToken: () => true,
  },
}));

import PostMenu, { postDeleteConsequence } from '@/components/PostMenu';
import CommentSection from '@/components/CommentSection';
import { useAuthStore } from '@/lib/store';
import type { User } from '@/lib/types';

const ME = { id: 7, email: 'me@test.invalid', username: 'me' } as User;

const comment = (over: Partial<Comment>): Comment =>
  ({
    id: 1,
    post_id: 10,
    author_user_id: ME.id,
    content: 'Mine.',
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    provenance: 'user_written',
    ...over,
  }) as Comment;

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ user: ME });
  deletePost.mockResolvedValue(undefined);
  deleteComment.mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  useAuthStore.setState({ user: null });
});

describe('post delete consequence copy', () => {
  it('states the real comment count with correct plurals', () => {
    expect(postDeleteConsequence(3)).toBe(
      "This permanently removes the post, its reactions and 3 comments. This can't be undone.",
    );
    expect(postDeleteConsequence(1)).toBe(
      "This permanently removes the post, its reactions and 1 comment. This can't be undone.",
    );
    expect(postDeleteConsequence(0)).toBe(
      "This permanently removes the post and its reactions. This can't be undone.",
    );
  });

  it('never invents a number when none was given', () => {
    expect(postDeleteConsequence(undefined)).toBe(
      "This permanently removes the post, its reactions and comments. This can't be undone.",
    );
  });
});

describe('PostMenu', () => {
  const openDialog = () => {
    fireEvent.click(screen.getByRole('button', { name: 'Post options' }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    return screen.getByRole('dialog');
  };

  it('confirms through the shared dialog, naming the dependent comments and reactions', () => {
    render(<PostMenu postId={5} commentCount={2} onDeleted={vi.fn()} />);
    const dialog = openDialog();
    expect(within(dialog).getByText('Delete post?')).toBeTruthy();
    expect(
      within(dialog).getByText(
        "This permanently removes the post, its reactions and 2 comments. This can't be undone.",
      ),
    ).toBeTruthy();
  });

  it('uses the generic wording without a count', () => {
    render(<PostMenu postId={5} onDeleted={vi.fn()} />);
    const dialog = openDialog();
    expect(
      within(dialog).getByText(
        "This permanently removes the post, its reactions and comments. This can't be undone.",
      ),
    ).toBeTruthy();
  });

  it('deletes and reports the id only after the server agrees', async () => {
    const onDeleted = vi.fn();
    render(<PostMenu postId={5} commentCount={0} onDeleted={onDeleted} />);
    const dialog = openDialog();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith(5));
    expect(deletePost).toHaveBeenCalledWith(5);
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('keeps the post and shows the error when the delete is refused', async () => {
    deletePost.mockRejectedValue(new Error('Not authorized to delete this post'));
    const onDeleted = vi.fn();
    render(<PostMenu postId={5} onDeleted={onDeleted} />);
    const dialog = openDialog();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete' }));
    expect(await within(dialog).findByText('Not authorized to delete this post')).toBeTruthy();
    expect(onDeleted).not.toHaveBeenCalled();
  });
});

describe('CommentSection author-only delete', () => {
  it('offers Delete on my comments only', async () => {
    getPostComments.mockResolvedValue([
      comment({ id: 1, content: 'Mine.' }),
      comment({ id: 2, content: 'Theirs.', author_user_id: 99 }),
      // A character comment by someone else arrives with the account stripped.
      comment({ id: 3, content: 'Hidden author.', author_user_id: null as unknown as number }),
    ]);
    render(<CommentSection postId={10} defaultExpanded />);
    await screen.findByText('Theirs.');

    expect(screen.getAllByRole('button', { name: 'Delete comment' })).toHaveLength(1);
    const mine = screen.getByText('Mine.').parentElement as HTMLElement;
    expect(within(mine).getByRole('button', { name: 'Delete comment' })).toBeTruthy();
  });

  it('offers nothing to a signed-out reader', async () => {
    useAuthStore.setState({ user: null });
    getPostComments.mockResolvedValue([comment({ id: 1 })]);
    render(<CommentSection postId={10} defaultExpanded />);
    await screen.findByText('Mine.');
    expect(screen.queryByRole('button', { name: 'Delete comment' })).toBeNull();
  });

  it('removes the comment, updates the count and reports the change', async () => {
    getPostComments.mockResolvedValue([
      comment({ id: 1, content: 'Mine.' }),
      comment({ id: 2, content: 'Theirs.', author_user_id: 99 }),
    ]);
    const onCommentCountChange = vi.fn();
    render(
      <CommentSection postId={10} defaultExpanded commentCount={2} onCommentCountChange={onCommentCountChange} />,
    );
    await screen.findByText('Mine.');

    fireEvent.click(screen.getByRole('button', { name: 'Delete comment' }));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText('Delete comment?')).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete' }));

    await waitFor(() => expect(screen.queryByText('Mine.')).toBeNull());
    expect(deleteComment).toHaveBeenCalledWith(1);
    expect(onCommentCountChange).toHaveBeenCalledWith(-1);
    expect(screen.getByText('Theirs.')).toBeTruthy();
    expect(screen.queryByRole('dialog')).toBeNull();

    // Collapsed label counts what is left.
    fireEvent.click(screen.getByRole('button', { name: 'Hide comments' }));
    expect(screen.getByRole('button', { name: 'Comments (1)' })).toBeTruthy();
  });

  it('keeps the comment when the delete fails', async () => {
    deleteComment.mockRejectedValue(new Error('Comment not found'));
    getPostComments.mockResolvedValue([comment({ id: 1, content: 'Mine.' })]);
    render(<CommentSection postId={10} defaultExpanded />);
    await screen.findByText('Mine.');

    fireEvent.click(screen.getByRole('button', { name: 'Delete comment' }));
    const dialog = screen.getByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete' }));

    expect(await within(dialog).findByText('Comment not found')).toBeTruthy();
    expect(screen.getByText('Mine.')).toBeTruthy();
  });
});
