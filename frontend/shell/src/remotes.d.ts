// Module Federation 動態 remote 的型別宣告。
// 實際模組由各 remote 的 remoteEntry.js 在執行期提供。
//
// 注意：用 inline `import(...)` 型別語法（而非頂層 import），
// 才能讓本檔維持「環境宣告（ambient）」而非模組擴充，否則 declare module 會失效。
declare module 'auth/AuthApp' {
  const AuthApp: import('react').ComponentType<
    import('../../contracts').AuthAppProps
  >;
  export default AuthApp;
}

declare module 'chat/ChatApp' {
  const ChatApp: import('react').ComponentType<
    import('../../contracts').ChatAppProps
  >;
  export default ChatApp;
}
