// 群組角色純權限判定（不碰 React / 網路），單獨單元測試。

export type Role = 'admin' | 'member';
export type RoleMap = Record<string, Role>;

/** userId 是否為該群 admin。 */
export function isAdmin(roles: RoleMap, userId: string): boolean {
  return roles[userId] === 'admin';
}

/** 群內 admin 人數。 */
export function adminCount(roles: RoleMap): number {
  return Object.values(roles).filter((r) => r === 'admin').length;
}

/** userId 是否為唯一的 admin（移除/降級會使群組無 admin）。 */
export function isLastAdmin(roles: RoleMap, userId: string): boolean {
  return isAdmin(roles, userId) && adminCount(roles) === 1;
}
