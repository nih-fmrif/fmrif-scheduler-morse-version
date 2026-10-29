const nextUrlNode = document.getElementById("auth-callback-next-url");
if (nextUrlNode) {
  try {
    const nextUrl = JSON.parse(nextUrlNode.textContent || '"/"');
    if (typeof nextUrl === "string" && nextUrl) {
      window.location.replace(nextUrl);
    }
  } catch (error) {
    // Leave user on fallback link if JSON parsing fails.
  }
}
