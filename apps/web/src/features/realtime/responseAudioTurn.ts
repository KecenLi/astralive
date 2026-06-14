export interface ResponseTurnFinishState {
  voiceResponsePending: boolean;
  assistantAudioDone: boolean;
  responseAudioTurnInProgress: boolean;
  playerActive: boolean;
}

export function shouldFinishResponseTurn(state: ResponseTurnFinishState) {
  if (state.responseAudioTurnInProgress) return false;
  if (!state.voiceResponsePending && !state.assistantAudioDone) return false;
  return !state.playerActive;
}
