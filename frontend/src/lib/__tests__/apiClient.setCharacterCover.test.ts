// @vitest-environment jsdom
/**
 * What `apiClient.setCharacterCover` actually puts on the wire.
 *
 * The server treats an OMITTED `cover_position_x/y` as "preserve the stored
 * framing" and an explicit value — 0.5 included — as "set it". That contract is
 * only honoured if the client can express omission, and it could not: the
 * parameters defaulted to 0.5 and were always serialised, so every caller that
 * meant "just change the picture" recentred the cover. Nothing caught it
 * because the backend suite posts hand-written bodies and the component suite
 * mocks `apiClient` away entirely. This exercises the REAL client against a
 * mocked `fetch`, which is the only place the request shape can be seen.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { apiClient } from '@/lib/apiClient';

const fetchMock = vi.fn();

const okJson = (body: unknown) =>
  ({
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
  }) as unknown as Response;

const sentBody = (): Record<string, unknown> => {
  const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  return JSON.parse(init.body as string);
};

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockResolvedValue(okJson({ cover_url: 'u', cover_position_y: 0.2, cover_position_x: 0.8 }));
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('apiClient.setCharacterCover request body', () => {
  it('omits both framing keys when the caller supplies none', async () => {
    await apiClient.setCharacterCover(42, 'character', 7);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/characters/42/cover');
    expect(init.method).toBe('POST');
    expect(sentBody()).toEqual({ image_type: 'character', image_id: 7 });
    expect(sentBody()).not.toHaveProperty('cover_position_x');
    expect(sentBody()).not.toHaveProperty('cover_position_y');
  });

  it('sends explicit framing exactly as given — including a deliberate centre', async () => {
    await apiClient.setCharacterCover(42, 'character', 7, 0.5, 0.5);
    expect(sentBody()).toEqual({
      image_type: 'character',
      image_id: 7,
      cover_position_y: 0.5,
      cover_position_x: 0.5,
    });
  });

  it('sends a non-centre framing with the axes the right way round (Y then X in the signature)', async () => {
    await apiClient.setCharacterCover(42, 'character', 7, 0.8, 0.25);
    expect(sentBody()).toMatchObject({ cover_position_y: 0.8, cover_position_x: 0.25 });
  });

  it('can set one axis and leave the other to the server', async () => {
    await apiClient.setCharacterCover(42, 'character', 7, 0.3);
    expect(sentBody()).toEqual({ image_type: 'character', image_id: 7, cover_position_y: 0.3 });
  });

  it('returns the framing the server reports, not what it sent', async () => {
    const result = await apiClient.setCharacterCover(42, 'character', 7);
    expect(result).toEqual({ cover_url: 'u', cover_position_y: 0.2, cover_position_x: 0.8 });
  });
});
