import type {
  ConfirmSubscriptionResult,
  RequestSubscriptionResult,
  UnsubscribePreviewResult,
  UnsubscribeResult,
} from "./types";

export interface RequestSubscriptionPayload {
  email: string;
}

export interface ConfirmSubscriptionPayload {
  token: string;
}

export interface UnsubscribePayload {
  token: string;
}

export type RequestSubscriptionResponse = RequestSubscriptionResult | { error: string };
export type ConfirmSubscriptionResponse = ConfirmSubscriptionResult | { error: string };
export type UnsubscribePreviewResponse = UnsubscribePreviewResult | { error: string };
export type UnsubscribeResponse = UnsubscribeResult | { error: string };
