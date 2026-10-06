/* Pulls attended by a player and every alt merged into them, from one
   { character: [pullKey, ...] } map (pullParticipation, or one boss's
   entry in bossParticipation). */
export function groupPulls(byCharacter, player, characterGroups) {
  if (!byCharacter) return 0;
  const characters = [player, ...((characterGroups && characterGroups[player]) || [])];
  return characters.reduce((total, c) => total + (byCharacter[c]?.length || 0), 0);
}
