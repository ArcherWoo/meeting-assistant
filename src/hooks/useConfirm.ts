import { useConfirmStore } from '@/stores/confirmStore';

export function useConfirm() {
  return useConfirmStore((state) => state.openConfirm);
}
