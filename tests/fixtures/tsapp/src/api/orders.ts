// Entrypoint. Reaches lodash.merge only via the barrel in ../lib.
import { normalizePayload } from "../lib";
import { OrderService } from "../services/order";

export function handleOrder(payload: unknown): unknown {
  const clean = normalizePayload(payload);
  return clean;
}

export function dispatch(): void {
  const svc = new OrderService();
  svc.handle();
}
