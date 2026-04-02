export type AppResourceKey =
  | 'roles'
  | 'skills'
  | 'knowledge'
  | 'knowhow'
  | 'llmProfiles'
  | 'users'
  | 'groups'
  | 'grants';

const APP_INVALIDATION_EVENT = 'zhishu:app-data-invalidated';

export function emitAppDataInvalidation(resources: AppResourceKey[]): void {
  window.dispatchEvent(new CustomEvent<AppResourceKey[]>(APP_INVALIDATION_EVENT, {
    detail: Array.from(new Set(resources)),
  }));
}

export function subscribeAppDataInvalidation(
  handler: (resources: AppResourceKey[]) => void,
): () => void {
  const listener = (event: Event) => {
    const customEvent = event as CustomEvent<AppResourceKey[]>;
    handler(Array.isArray(customEvent.detail) ? customEvent.detail : []);
  };

  window.addEventListener(APP_INVALIDATION_EVENT, listener as EventListener);
  return () => {
    window.removeEventListener(APP_INVALIDATION_EVENT, listener as EventListener);
  };
}

export function hasInvalidatedResource(
  resources: AppResourceKey[],
  targets: AppResourceKey[],
): boolean {
  return resources.some((resource) => targets.includes(resource));
}
