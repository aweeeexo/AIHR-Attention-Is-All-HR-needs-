import React from 'react';

export function Tag({ kind, children }) {
  return <span className={`tag ${kind}`}>{children}</span>;
}
