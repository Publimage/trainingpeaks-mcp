"""Read-only image transformation runtime capability inventory."""
import importlib.util, json, shutil
def main():
    out={
      "pillow": importlib.util.find_spec("PIL") is not None,
      "imagemagick_convert": shutil.which("convert"),
      "imagemagick_magick": shutil.which("magick"),
      "ffmpeg": shutil.which("ffmpeg"),
    }
    print("IMAGE_RUNTIME_CAPABILITY_INVENTORY")
    print(json.dumps(out,sort_keys=True))
    return 0
if __name__=="__main__":
    raise SystemExit(main())
