from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, ttk
from urllib.parse import urlencode

import requests


DEFAULT_API_BASE = "http://127.0.0.1:8000"


class ProductImageSearchApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("商品图片相似检索")
        self.geometry("1120x760")
        self.minsize(960, 640)

        self.api_base = tk.StringVar(value=DEFAULT_API_BASE)
        self.category = tk.StringVar(value="MLM194295")
        self.global_search = tk.BooleanVar(value=False)
        self.score_threshold = tk.StringVar(value="0.70")
        self.image_limit = tk.StringVar(value="100")
        self.product_limit = tk.StringVar(value="20")
        self.file_path = tk.StringVar(value="")
        self.image_url = tk.StringVar(value="")

        self.import_site = tk.StringVar(value="ml_mx")
        self.import_limit = tk.StringVar(value="")
        self.import_status = tk.StringVar(value="等待导入任务")
        self.import_counts = tk.StringVar(value="Mongo - / Qdrant -")
        self.import_job_ids: list[str] = []

        self._build_ui()

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)

        top = ttk.Frame(root)
        top.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(top, text="API").pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=self.api_base, width=38).pack(side=tk.LEFT, padx=8)
        ttk.Button(top, text="健康检查", command=self.check_health).pack(side=tk.LEFT)

        tabs = ttk.Notebook(root)
        tabs.pack(fill=tk.BOTH, expand=True)

        search_tab = ttk.Frame(tabs, padding=12)
        import_tab = ttk.Frame(tabs, padding=12)
        tabs.add(search_tab, text="搜图")
        tabs.add(import_tab, text="数据导入")

        self._build_search_tab(search_tab)
        self._build_import_tab(import_tab)

    def _build_search_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(8, weight=1)

        ttk.Label(parent, text="类目").grid(row=0, column=0, sticky=tk.W, pady=4)
        ttk.Entry(parent, textvariable=self.category).grid(row=0, column=1, sticky=tk.EW, pady=4)
        ttk.Checkbutton(parent, text="全局搜索", variable=self.global_search).grid(row=1, column=1, sticky=tk.W, pady=4)

        ttk.Label(parent, text="本地图片").grid(row=2, column=0, sticky=tk.W, pady=4)
        file_row = ttk.Frame(parent)
        file_row.grid(row=2, column=1, sticky=tk.EW, pady=4)
        file_row.columnconfigure(0, weight=1)
        ttk.Entry(file_row, textvariable=self.file_path).grid(row=0, column=0, sticky=tk.EW)
        ttk.Button(file_row, text="选择", command=self.choose_file).grid(row=0, column=1, padx=(8, 0))

        ttk.Label(parent, text="图片 URL").grid(row=3, column=0, sticky=tk.W, pady=4)
        ttk.Entry(parent, textvariable=self.image_url).grid(row=3, column=1, sticky=tk.EW, pady=4)

        opts = ttk.Frame(parent)
        opts.grid(row=4, column=1, sticky=tk.W, pady=4)
        ttk.Label(opts, text="图片召回").pack(side=tk.LEFT)
        ttk.Entry(opts, textvariable=self.image_limit, width=8).pack(side=tk.LEFT, padx=(6, 16))
        ttk.Label(opts, text="商品返回").pack(side=tk.LEFT)
        ttk.Entry(opts, textvariable=self.product_limit, width=8).pack(side=tk.LEFT, padx=(6, 16))
        ttk.Label(opts, text="阈值").pack(side=tk.LEFT)
        ttk.Entry(opts, textvariable=self.score_threshold, width=8).pack(side=tk.LEFT, padx=(6, 0))

        actions = ttk.Frame(parent)
        actions.grid(row=5, column=1, sticky=tk.W, pady=8)
        ttk.Button(actions, text="搜图", command=self.search).pack(side=tk.LEFT)
        ttk.Button(actions, text="清空结果", command=lambda: self.results.delete("1.0", tk.END)).pack(side=tk.LEFT, padx=8)

        self.search_status = tk.StringVar(value="等待检索")
        ttk.Label(parent, textvariable=self.search_status).grid(row=6, column=1, sticky=tk.W, pady=4)
        self.results = tk.Text(parent, height=22, wrap=tk.WORD)
        self.results.grid(row=8, column=0, columnspan=2, sticky=tk.NSEW, pady=(8, 0))

    def _build_import_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)

        ttk.Label(parent, text="类目 ID").grid(row=0, column=0, sticky=tk.NW, pady=4)
        self.import_categories = tk.Text(parent, height=7, wrap=tk.WORD)
        self.import_categories.insert("1.0", "MLM2789")
        self.import_categories.grid(row=0, column=1, sticky=tk.EW, pady=4)

        ttk.Label(parent, text="站点").grid(row=1, column=0, sticky=tk.W, pady=4)
        ttk.Entry(parent, textvariable=self.import_site, width=18).grid(row=1, column=1, sticky=tk.W, pady=4)

        ttk.Label(parent, text="限制数量").grid(row=2, column=0, sticky=tk.W, pady=4)
        ttk.Entry(parent, textvariable=self.import_limit, width=18).grid(row=2, column=1, sticky=tk.W, pady=4)

        buttons = ttk.Frame(parent)
        buttons.grid(row=3, column=1, sticky=tk.W, pady=10)
        ttk.Button(buttons, text="批量导入并建索引", command=self.start_import).pack(side=tk.LEFT)
        ttk.Button(buttons, text="终止当前类目", command=self.stop_import).pack(side=tk.LEFT, padx=8)

        ttk.Label(parent, textvariable=self.import_status, font=("", 12, "bold")).grid(row=4, column=1, sticky=tk.W, pady=(8, 2))
        ttk.Label(parent, textvariable=self.import_counts, font=("", 14, "bold")).grid(row=5, column=1, sticky=tk.W)
        ttk.Label(parent, text="多个类目可用换行、逗号、空格分隔；导入和建索引按 sku_id 去重。").grid(row=6, column=1, sticky=tk.W, pady=8)

        self.import_table = ttk.Treeview(parent, columns=("category", "status", "counts"), show="headings", height=10)
        self.import_table.heading("category", text="类目")
        self.import_table.heading("status", text="状态")
        self.import_table.heading("counts", text="数量")
        self.import_table.column("category", width=180, anchor=tk.W)
        self.import_table.column("status", width=160, anchor=tk.W)
        self.import_table.column("counts", width=220, anchor=tk.W)
        self.import_table.grid(row=7, column=1, sticky=tk.NSEW, pady=(8, 0))
        parent.rowconfigure(7, weight=1)

    def choose_file(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("图片", "*.jpg *.jpeg *.png *.webp *.bmp"), ("所有文件", "*.*")])
        if path:
            self.file_path.set(path)
            self.image_url.set("")

    def check_health(self) -> None:
        self._run_bg(lambda: self._health_worker())

    def _health_worker(self) -> None:
        try:
            data = requests.get(f"{self.api_base.get().rstrip('/')}/health", timeout=10).json()
            self.search_status.set(f"服务正常: {data}")
        except Exception as exc:
            self.search_status.set(f"服务异常: {exc}")

    def search(self) -> None:
        self._run_bg(self._search_worker)

    def _search_worker(self) -> None:
        self.search_status.set("正在检索...")
        try:
            params = {
                "image_limit": self.image_limit.get() or "100",
                "product_limit": self.product_limit.get() or "20",
                "global_search": "true" if self.global_search.get() else "false",
            }
            if not self.global_search.get():
                params["category_id"] = self.category.get().strip()
            if self.score_threshold.get().strip():
                params["score_threshold"] = self.score_threshold.get().strip()

            api = self.api_base.get().rstrip("/")
            if self.file_path.get().strip():
                with open(self.file_path.get().strip(), "rb") as file:
                    resp = requests.post(f"{api}/search?{urlencode(params)}", files={"file": file}, timeout=180)
            elif self.image_url.get().strip():
                params["url"] = self.image_url.get().strip()
                resp = requests.post(f"{api}/search-url?{urlencode(params)}", timeout=180)
            else:
                self.search_status.set("请选择图片或输入 URL。")
                return

            resp.raise_for_status()
            data = resp.json()
            self._render_results(data)
            self.search_status.set("检索完成")
        except Exception as exc:
            self.search_status.set(f"检索失败: {exc}")

    def _render_results(self, data: dict) -> None:
        self.results.delete("1.0", tk.END)
        self.results.insert(tk.END, f"范围: {'全局' if data.get('global_search') else data.get('category_id')}\n")
        self.results.insert(tk.END, f"图片命中: {data.get('image_hits')} / 商品返回: {len(data.get('products', []))}\n\n")
        for index, item in enumerate(data.get("products", []), start=1):
            product = item.get("product") or {}
            best = item.get("best_image") or {}
            image_url = best.get("image_url") or product.get("image_url") or product.get("pic_url") or ""
            self.results.insert(
                tk.END,
                f"{index}. SKU: {item.get('sku_id')}  相似度: {float(item.get('score', 0)):.6f}\n"
                f"   类目: {product.get('category_id') or best.get('category_id') or '-'}  "
                f"价格: {product.get('active_price') or best.get('active_price') or '-'}  "
                f"订单: {product.get('total_order') or best.get('total_order') or '-'}\n"
                f"   图片: {image_url}\n\n",
            )

    def start_import(self) -> None:
        self._run_bg(self._start_import_worker)

    def _start_import_worker(self) -> None:
        text = self.import_categories.get("1.0", tk.END).strip()
        category_ids = ",".join(parse_category_ids(text))
        if not category_ids:
            self.import_status.set("请输入类目 ID。")
            return

        params = {
            "category_ids": category_ids,
            "site": self.import_site.get().strip() or "ml_mx",
            "import_batch_size": "500",
            "index_batch_size": "32",
            "skip_existing": "true",
        }
        if self.import_limit.get().strip():
            params["limit"] = self.import_limit.get().strip()

        try:
            api = self.api_base.get().rstrip("/")
            resp = requests.post(f"{api}/import-categories?{urlencode(params)}", timeout=30)
            resp.raise_for_status()
            data = resp.json()
            self.import_job_ids = [job["job_id"] for job in data.get("jobs", [])]
            self.import_status.set(f"已提交 {len(self.import_job_ids)} 个类目，按 sku_id 去重")
            self._render_import_jobs(data.get("jobs", []))
            self.after(1000, self.poll_import_jobs)
        except Exception as exc:
            self.import_status.set(f"提交失败: {exc}")

    def poll_import_jobs(self) -> None:
        if not self.import_job_ids:
            return
        self._run_bg(self._poll_import_jobs_worker)

    def _poll_import_jobs_worker(self) -> None:
        api = self.api_base.get().rstrip("/")
        jobs = self._fetch_import_jobs(api, self.import_job_ids)
        if not jobs:
            self.import_status.set("暂时读取不到任务状态")
            return

        done = len([job for job in jobs if job.get("status") in {"completed", "failed", "cancelled"}])
        active = next((job for job in jobs if job.get("status") not in {"completed", "failed", "cancelled"}), jobs[-1])
        self._render_import_jobs(jobs)
        self.import_status.set(f"批量导入 {done}/{len(jobs)}：{active.get('category_id')} {active.get('stage')}")
        self.import_counts.set(f"Mongo {active.get('mongo_count', '-')} / Qdrant {active.get('qdrant_count', '-')}")
        if done < len(jobs):
            self.after(5000, self.poll_import_jobs)

    def _fetch_import_jobs(self, api: str, job_ids: list[str]) -> list[dict]:
        try:
            params = urlencode({"job_ids": ",".join(job_ids)})
            resp = requests.get(f"{api}/import-categories-status?{params}", timeout=20)
            if resp.ok:
                return resp.json().get("jobs", [])
        except Exception:
            pass

        jobs = []
        for job_id in job_ids:
            try:
                resp = requests.get(f"{api}/import-category/{job_id}", timeout=15)
                if resp.ok:
                    jobs.append(resp.json())
            except Exception:
                pass
        return jobs

    def _render_import_jobs(self, jobs: list[dict]) -> None:
        for item in self.import_table.get_children():
            self.import_table.delete(item)
        for job in jobs:
            self.import_table.insert(
                "",
                tk.END,
                values=(
                    job.get("category_id", "-"),
                    job.get("stage") or job.get("status") or "-",
                    f"Mongo {job.get('mongo_count', '-')} / Qdrant {job.get('qdrant_count', '-')}",
                ),
            )

    def stop_import(self) -> None:
        self._run_bg(self._stop_import_worker)

    def _stop_import_worker(self) -> None:
        text = self.import_categories.get("1.0", tk.END).strip()
        categories = parse_category_ids(text)
        if not categories and not self.import_job_ids:
            self.import_status.set("请输入要终止的类目 ID。")
            return
        try:
            api = self.api_base.get().rstrip("/")
            if self.import_job_ids:
                params = urlencode({"job_ids": ",".join(self.import_job_ids)})
                resp = requests.post(f"{api}/import-categories-cancel?{params}", timeout=30)
                resp.raise_for_status()
                data = resp.json()
                jobs = data.get("jobs", [])
                self._render_import_jobs(jobs)
                self.import_status.set(f"已请求终止 {data.get('job_count', 0)} 个任务")
                if jobs:
                    active = jobs[0]
                    self.import_counts.set(f"Mongo {active.get('mongo_count', '-')} / Qdrant {active.get('qdrant_count', '-')}")
                return
            params = urlencode({"category_id": categories[0], "site": self.import_site.get().strip() or "ml_mx"})
            resp = requests.post(f"{api}/stop-category?{params}", timeout=30)
            resp.raise_for_status()
            data = resp.json()
            self.import_status.set(f"已请求终止 {categories[0]}")
            self.import_counts.set(f"Mongo {data.get('mongo_count', '-')} / Qdrant {data.get('qdrant_count', '-')}")
        except Exception as exc:
            self.import_status.set(f"终止失败: {exc}")

    def _run_bg(self, func) -> None:
        threading.Thread(target=func, daemon=True).start()


def parse_category_ids(text: str) -> list[str]:
    import re

    return list(dict.fromkeys(item.strip() for item in re.split(r"[\s,，;；]+", text) if item.strip()))


def main() -> None:
    app = ProductImageSearchApp()
    app.mainloop()


if __name__ == "__main__":
    main()
