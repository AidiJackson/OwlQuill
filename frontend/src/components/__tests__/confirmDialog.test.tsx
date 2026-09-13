// @vitest-environment jsdom
//
// ConfirmDialog is the one place a permanent deletion is confirmed, so its
// safety properties are pinned: type-to-confirm gates the button, Escape and
// backdrop only ever cancel, and `busy` freezes everything.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

import ConfirmDialog from '@/components/ConfirmDialog';

afterEach(cleanup);

function renderDialog(overrides: Partial<React.ComponentProps<typeof ConfirmDialog>> = {}) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  render(
    <ConfirmDialog
      open
      title="Delete character"
      confirmLabel="Delete character"
      danger
      onConfirm={onConfirm}
      onCancel={onCancel}
      {...overrides}
    >
      <p>This cannot be undone.</p>
    </ConfirmDialog>,
  );
  return { onConfirm, onCancel };
}

describe('ConfirmDialog', () => {
  it('renders nothing when closed', () => {
    render(
      <ConfirmDialog open={false} title="x" confirmLabel="x" onConfirm={() => {}} onCancel={() => {}} />,
    );
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('confirms only after the exact name is typed', () => {
    const { onConfirm } = renderDialog({ confirmText: 'Bertie' });
    const confirm = screen.getByRole('button', { name: 'Delete character' });
    expect(confirm).toHaveProperty('disabled', true);

    fireEvent.change(screen.getByLabelText('Type Bertie to confirm'), { target: { value: 'bertie' } });
    expect(confirm).toHaveProperty('disabled', true);

    fireEvent.change(screen.getByLabelText('Type Bertie to confirm'), { target: { value: ' Bertie ' } });
    expect(confirm).toHaveProperty('disabled', false);
    fireEvent.click(confirm);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('Escape and backdrop cancel and never confirm', () => {
    const { onConfirm, onCancel } = renderDialog();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onCancel).toHaveBeenCalledTimes(1);
    // The backdrop is the dialog's parent.
    fireEvent.click(screen.getByRole('dialog').parentElement as HTMLElement);
    expect(onCancel).toHaveBeenCalledTimes(2);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('cannot be dismissed or re-submitted while busy', () => {
    const { onConfirm, onCancel } = renderDialog({ busy: true });
    fireEvent.keyDown(window, { key: 'Escape' });
    fireEvent.click(screen.getByRole('dialog').parentElement as HTMLElement);
    fireEvent.click(screen.getByRole('button', { name: /Delete character/ }));
    expect(onCancel).not.toHaveBeenCalled();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('focuses Cancel first for a danger dialog', () => {
    renderDialog();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Cancel' }));
  });

  it('shows the last error inside the dialog', () => {
    renderDialog({ error: 'Could not delete right now.' });
    expect(screen.getByRole('alert').textContent).toContain('Could not delete right now.');
  });
});
