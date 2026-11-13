import React from 'react';

// Скелетоны повторяют форму настоящего содержимого (скилл, B9): вместо крутящихся индикаторов.

export function RankingSkeleton({ rows = 3 }) {
  return (
    <div className="skeleton-card" aria-hidden="true">
      <div className="skeleton line w-40" />
      <div className="skeleton line w-70" />
      {Array.from({ length: rows }, (_, index) => (
        <div className="skeleton-row" key={index}>
          <div className="skeleton circle" />
          <div className="skeleton-stack">
            <div className="skeleton line w-60" />
            <div className="skeleton line w-30" />
          </div>
          <div className="skeleton block" />
        </div>
      ))}
    </div>
  );
}

export function PageSkeleton() {
  return (
    <div className="page-skeleton" role="status" aria-live="polite">
      <span className="sr-only">Загружаем результат</span>
      <div className="skeleton line w-30 tall" aria-hidden="true" />
      <div className="skeleton line w-60" aria-hidden="true" />
      <RankingSkeleton />
    </div>
  );
}
