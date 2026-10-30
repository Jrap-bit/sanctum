'use client';
export default function Error({ error, reset }: { error: Error; reset: () => void }) { return <div className="center-screen" role="alert"><div><h1>Something went wrong</h1><p>{error.message}</p><button onClick={reset} className="button primary">Try again</button></div></div>; }
