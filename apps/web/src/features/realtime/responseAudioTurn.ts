export interface ResponseTurnFinishState {
  voiceResponsePending: boolean;
  assistantAudioDone: boolean;
  responseAudioTurnInProgress: boolean;
  playerActive: boolean;
  force?: boolean;
}

export function shouldFinishResponseTurn(state: ResponseTurnFinishState) {
  if (state.force) return true;
  if (state.responseAudioTurnInProgress) return false;
  if (!state.voiceResponsePending && !state.assistantAudioDone) return false;
  return !state.playerActive;
}
