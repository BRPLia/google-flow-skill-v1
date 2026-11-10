"""Identity observed in Flow's DOM, independent of CDN host and thumbnail size."""

MEDIA_KEY_JS = r"""node => {
    if (!node) return null;
    const explicit = node.getAttribute('data-media-id');
    if (explicit) return explicit;
    const raw = node.getAttribute('src');
    if (!raw) return null;
    const url = new URL(raw, document.baseURI);
    const uuid = url.searchParams.get('name');
    if (uuid) return uuid;
    if (url.pathname.includes('/asb/')) return url.pathname.split('/asb/')[1].split('=')[0];
    const match = url.pathname.match(/\/(?:image|video)\/([a-f0-9-]{36})(?:\/|$)/i);
    return match ? match[1] : null;
}"""

CARD_MEDIA_JS = "c => c.querySelector('img[data-media-id], img[src], video[src]')"
