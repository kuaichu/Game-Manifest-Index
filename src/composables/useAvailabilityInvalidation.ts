const AVAILABILITY_INVALIDATION_EVENT = "gmi-availability-invalidated";
const AVAILABILITY_INVALIDATION_STORAGE_KEY = "gmi-availability-invalidated-at";

export function useAvailabilityInvalidation() {
  let lastInvalidatedOperationJobId: string | null = null;
  let availabilityInvalidationSequence = 0;

  function notifyAvailabilityInvalidated(jobId: string): void {
    if (lastInvalidatedOperationJobId === jobId) return;
    lastInvalidatedOperationJobId = jobId;
    window.dispatchEvent(new CustomEvent(AVAILABILITY_INVALIDATION_EVENT, { detail: { jobId } }));
    try {
      localStorage.setItem(AVAILABILITY_INVALIDATION_STORAGE_KEY, `${jobId}:${Date.now()}`);
    } catch {
      // Storage unavailable; the same-tab CustomEvent has already fired.
    }
  }

  function nextVersionProbeInvalidationId(domainId: string, version: string): string {
    availabilityInvalidationSequence += 1;
    return `version-probe:${domainId}:${version}:${Date.now()}:${availabilityInvalidationSequence}`;
  }

  return { notifyAvailabilityInvalidated, nextVersionProbeInvalidationId };
}

export type AvailabilityInvalidation = ReturnType<typeof useAvailabilityInvalidation>;
