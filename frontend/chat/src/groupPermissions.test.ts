import { describe, expect, it } from 'vitest';

import { adminCount, isAdmin, isLastAdmin } from './groupPermissions';

const roles = { a: 'admin', b: 'member', c: 'admin' } as Record<string, 'admin' | 'member'>;

describe('groupPermissions', () => {
  it('isAdmin', () => {
    expect(isAdmin(roles, 'a')).toBe(true);
    expect(isAdmin(roles, 'b')).toBe(false);
    expect(isAdmin(roles, 'zzz')).toBe(false);
  });
  it('adminCount', () => {
    expect(adminCount(roles)).toBe(2);
    expect(adminCount({ a: 'member' })).toBe(0);
  });
  it('isLastAdmin', () => {
    expect(isLastAdmin({ a: 'admin', b: 'member' }, 'a')).toBe(true);
    expect(isLastAdmin(roles, 'a')).toBe(false); // 兩位 admin
    expect(isLastAdmin(roles, 'b')).toBe(false); // 非 admin
  });
});
