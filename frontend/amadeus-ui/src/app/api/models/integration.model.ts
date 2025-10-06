export interface ExchangeDescriptor {
  code: string;
  name: string;
}

export interface ExchangeListResponse {
  exchanges: ExchangeDescriptor[];
}
