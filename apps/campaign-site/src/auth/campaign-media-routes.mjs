const id = "[0-9A-HJKMNP-TV-Z]{26}";
export const campaignMediaKey =
  /^campaigns\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(png|jpg|webp)$/;
export function campaignMediaRoute(path, method) {
  if (path === "/_emdash/api/media" && method === "GET") return "list";
  if (path === "/_emdash/api/media/upload-url" && method === "POST")
    return "reserve";
  if (new RegExp(`^/_emdash/api/media/${id}$`).test(path) && method === "GET")
    return "get";
  if (
    new RegExp(`^/_emdash/api/media/${id}/upload$`).test(path) &&
    method === "PUT"
  )
    return "upload";
  if (
    new RegExp(`^/_emdash/api/media/${id}/confirm$`).test(path) &&
    method === "POST"
  )
    return "confirm";
  if (
    path.startsWith("/_emdash/api/media/file/") &&
    method === "GET" &&
    campaignMediaKey.test(path.slice("/_emdash/api/media/file/".length))
  )
    return "file";
  return null;
}
