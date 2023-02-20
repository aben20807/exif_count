import argparse
import datetime
from fractions import Fraction
import multiprocessing
from pathlib import Path
import signal
from PIL import Image
from PIL.ExifTags import TAGS
from tqdm.asyncio import tqdm
import termplotlib as tpl


STATISTIC_KEYS = [
    "DateTimeOriginal",
    "Model",
    "LensModel",
    "FNumber",
    "ExposureTime",
    "ISOSpeedRatings",
    "FocalLength",
]


def setup(the_lock):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    # Lock: https://stackoverflow.com/a/68820192
    global lock
    lock = the_lock


def make_statistic(in_path: Path, shared_dict):

    with Image.open(in_path) as img:
        exif = img._getexif()

        if exif is None:
            # print(f"Something wrong: exif is None ", in_path)
            return

        exif_result = {}
        for (tag, value) in exif.items():
            key = TAGS.get(tag, tag)
            exif_result[key] = str(value)

        value = ""
        for key in STATISTIC_KEYS:
            if key not in exif_result.keys():
                # print(f"Something wrong: no data ", in_path)
                return
            elif key == "DateTimeOriginal":  # convert time to date only
                value = str(exif_result[key]).split(" ")[0].replace(":", "-", 2)
            else:
                value = str(exif_result[key]).strip(
                    "\x00"
                )  # LensModel has some \x00 char...

            with lock:
                if str(value) not in shared_dict[str(key)].keys():
                    shared_dict[str(key)][str(value)] = 1
                else:
                    shared_dict[str(key)][str(value)] += 1


def pbar_update(_):
    pbar.update(1)


def get_statistic_dict(in_dir: str, recursive: bool, img_exts: str, dir_filter:str) -> dict:
    files = Path(in_dir).rglob("*") if recursive else Path(in_dir).glob("*")
    allowed_exts = ["." + str(i).lower() for i in img_exts.split(",")]
    files = list(filter(lambda file: str(file.suffix).lower() in allowed_exts, files))
    files = list(filter(lambda file: dir_filter in str(file.parent), files))

    dict_v = {}
    lock = multiprocessing.Lock()
    global pbar
    pbar = tqdm(total=len(files))

    with multiprocessing.Manager() as manager:
        shared_dict = manager.dict()
        for k in STATISTIC_KEYS:
            shared_dict[k] = manager.dict()
        tasks = []
        pool = multiprocessing.Pool(
            multiprocessing.cpu_count(), initializer=setup, initargs=(lock,)
        )
        for file in files:

            in_path = file.absolute()
            tasks.append(
                pool.apply_async(
                    make_statistic, (in_path, shared_dict), callback=pbar_update
                )
            )

        for task in tasks:
            try:
                task.get(10)
            except multiprocessing.TimeoutError:
                print("TLE")
                continue
            except KeyboardInterrupt:
                pool.terminate()
                pool.join()
                return 1

        pool.close()
        pool.join()
        pbar.close()

        # convert to normal dict
        for k, v in dict(shared_dict).items():
            dict_v[k] = dict(v)
    return dict_v


def plot_statistic_dict(statistic_result):
    for k in statistic_result:
        # sort
        sort_lambda = lambda item: item[0]
        if k == "ExposureTime":
            sort_lambda = lambda item: Fraction(item[0])
        elif k == "FNumber" or k == "FocalLength":
            sort_lambda = lambda item: float(item[0])
        elif k == "ISOSpeedRatings":
            sort_lambda = lambda item: int(item[0])
        elif k == "DateTimeOriginal":
            sort_lambda = lambda item: datetime.date.fromisoformat(item[0])
        (keys, values) = zip(*sorted(statistic_result[k].items(), key=sort_lambda))

        print(f"\n[{k}]")
        plot_labels = list(keys)
        plot_values = [int(v) for v in list(values)]
        if k == "ExposureTime":
            plot_labels = [f"{Fraction(v).limit_denominator()}" for v in list(keys)]
        fig = tpl.figure()
        fig.barh(plot_values, plot_labels, force_ascii=True)
        fig.show()


def get_args():
    """Init argparser and return the args from cli."""
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "-s", "--src", help="input dir (required)", type=str, required=True
    )
    parser.add_argument(
        "-r", "--recursive", help="recursively process", action="store_true"
    )
    parser.add_argument(
        "--dir_filter", help="included substring in parent directries", type=str, default=""
    )
    parser.add_argument(
        "--img_exts",
        help="support extensions for processed photos (case insensitive)",
        type=str,
        default="jpg,jpeg,png,tiff",
    )
    return parser.parse_args()


def cli():
    args = get_args()
    print(f"args: {args}")
    statistic_result = get_statistic_dict(args.src, args.recursive, args.img_exts, args.dir_filter)
    if len(statistic_result["DateTimeOriginal"]) > 0:
        plot_statistic_dict(statistic_result)


if __name__ == "__main__":
    cli()
