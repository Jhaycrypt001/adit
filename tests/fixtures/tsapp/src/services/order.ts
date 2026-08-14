// Exercises this.method() binding and a class-method call chain.
export class OrderService {
  handle(): void {
    this.validate();
  }

  validate(): void {
    this.audit();
  }

  audit(): void {
    // leaf
  }
}
