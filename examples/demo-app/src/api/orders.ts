// Entrypoint. Two distinct routes into lodash, one reachable to a vulnerable
// symbol and one not -- which is the contrast the whole tool exists to draw.
import { normalizePayload } from "../lib";
import { scrubOrder } from "../sanitise";
import { OrderService } from "../services/order";

export function handleOrder(payload: unknown): unknown {
  const clean = normalizePayload(payload);
  return scrubOrder(clean);
}

export function dispatch(): void {
  const svc = new OrderService();
  svc.handle();
}
