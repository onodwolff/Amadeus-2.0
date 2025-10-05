export type InstrumentType = 'spot' | 'future' | 'perpetual' | 'option' | string;

export interface Instrument {
  instrument_id: string;
  symbol: string;
  venue: string;
  type: InstrumentType;
  base_currency?: string;
  quote_currency?: string;
  tick_size?: number;
  lot_size?: number;
  min_notional?: number;
  contract_size?: number;
  expiry?: string;
}

export interface InstrumentsResponse {
  instruments: Instrument[];
}
