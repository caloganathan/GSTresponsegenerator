import { useState } from 'react';

/**
 * Google Lens-style interactive document & OCR bounding-box viewer.
 *
 * Renders the uploaded notice page/image with an animated scan sweep while
 * extracting, then overlays confidence-coded bounding boxes that users can
 * hover or click to inspect and copy text directly from the scan.
 */
export default function LensScanner({
  pages = [],
  scanning = false,
  localPreviewUrl = '',
  extractedText = '',
}) {
  const [pageIndex, setPageIndex] = useState(0);
  const [selectedBox, setSelectedBox] = useState(null);
  const [showOverlay, setShowOverlay] = useState(true);
  const [copied, setCopied] = useState(false);

  const safeIndex = Math.min(pageIndex, Math.max(0, pages.length - 1));
  const currentPage = pages[safeIndex] || null;
  const imageSrc = currentPage?.image || localPreviewUrl;
  const boxes = currentPage?.boxes || [];

  const copyText = async (value) => {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };

  if (!imageSrc) {
    return (
      <div className="lens-empty">
        <div className="lens-empty-badge">Text Document</div>
        <p className="muted">
          No page image preview is available for this file format, but the full
          text was extracted below.
        </p>
        {extractedText && (
          <pre className="lens-text-fallback">{extractedText.slice(0, 1800)}</pre>
        )}
      </div>
    );
  }

  return (
    <div className="lens-container">
      <div className="lens-toolbar">
        <div className="lens-toolbar-left">
          <span className="lens-dot" />
          <span className="lens-title">
            {scanning ? 'Scanning notice with local OCR…' : 'Lens Scan Overlay'}
          </span>
          {!scanning && boxes.length > 0 && (
            <span className="lens-count">{boxes.length} text regions</span>
          )}
        </div>

        <div className="lens-toolbar-right">
          {boxes.length > 0 && (
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              onClick={() => setShowOverlay((v) => !v)}
            >
              {showOverlay ? 'Hide Boxes' : 'Show Boxes'}
            </button>
          )}
          {pages.length > 1 && (
            <div className="lens-pager">
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                disabled={safeIndex === 0}
                onClick={() => {
                  setSelectedBox(null);
                  setPageIndex((i) => Math.max(0, i - 1));
                }}
              >
                ‹
              </button>
              <span className="lens-page-label">
                Page {safeIndex + 1} / {pages.length}
              </span>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                disabled={safeIndex >= pages.length - 1}
                onClick={() => {
                  setSelectedBox(null);
                  setPageIndex((i) => Math.min(pages.length - 1, i + 1));
                }}
              >
                ›
              </button>
            </div>
          )}
        </div>
      </div>

      <div className="lens-stage">
        <div className="lens-canvas">
          <img
            src={imageSrc}
            alt={`Notice page ${safeIndex + 1}`}
            className="lens-image"
          />

          {scanning && (
            <div className="lens-scan-overlay" aria-hidden="true">
              <div className="lens-scan-beam" />
              <div className="lens-scan-grid" />
            </div>
          )}

          {!scanning && showOverlay && boxes.length > 0 && (
            <div className="lens-boxes" aria-label="Detected text regions">
              {boxes.map((box, idx) => {
                const lowConf = box.confidence < 0.8;
                const isSelected = selectedBox === idx;
                return (
                  <button
                    key={`${idx}-${box.x}-${box.y}`}
                    type="button"
                    title={`${box.text} (${Math.round(box.confidence * 100)}%)`}
                    onClick={() => setSelectedBox(isSelected ? null : idx)}
                    className={`lens-box ${lowConf ? 'lens-box-amber' : 'lens-box-ok'} ${
                      isSelected ? 'lens-box-selected' : ''
                    }`}
                    style={{
                      left: `${box.x * 100}%`,
                      top: `${box.y * 100}%`,
                      width: `${Math.max(box.w * 100, 0.8)}%`,
                      height: `${Math.max(box.h * 100, 1.0)}%`,
                    }}
                  />
                );
              })}
            </div>
          )}
        </div>
      </div>

      {selectedBox !== null && boxes[selectedBox] && (
        <div className="lens-inspector">
          <div className="lens-inspector-meta">
            <span
              className={`lens-conf-pill ${
                boxes[selectedBox].confidence < 0.8 ? 'amber' : 'ok'
              }`}
            >
              {Math.round(boxes[selectedBox].confidence * 100)}% confidence
            </span>
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              onClick={() => copyText(boxes[selectedBox].text)}
            >
              {copied ? 'Copied!' : 'Copy text'}
            </button>
          </div>
          <div className="lens-inspector-text">{boxes[selectedBox].text}</div>
        </div>
      )}

      {!scanning && boxes.length > 0 && (
        <div className="lens-legend">
          <span>
            <i className="legend-swatch ok" /> High confidence (&ge;80%)
          </span>
          <span>
            <i className="legend-swatch amber" /> Review recommended (&lt;80%)
          </span>
          <span className="muted">Click any box to inspect</span>
        </div>
      )}
    </div>
  );
}
