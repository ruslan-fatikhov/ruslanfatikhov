window.MountainsData = (() => {
  async function load() {
    const response = await fetch("/api/mountains", { headers: { Accept: "application/json" } });
    if (!response.ok) {
      throw new Error("Failed to load mountains data");
    }
    return response.json();
  }

  return { load };
})();
