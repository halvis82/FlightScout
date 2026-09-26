// An error with an HTTP status, shared by the API routes and the guest router
// (which runs the same validation in the browser).
export class HttpError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
