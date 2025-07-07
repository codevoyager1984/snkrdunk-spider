import requests
from bs4 import BeautifulSoup
import re
import json
from urllib.parse import urljoin, urlparse
import time
from concurrent.futures import ThreadPoolExecutor
import threading
import os
from datetime import datetime
import glob
from loguru import logger

class SnkrDunkSpider:
    def __init__(self):
        self.base_url = 'https://snkrdunk.com'
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        self.lock = threading.Lock()
        
        # 创建结果目录
        self.setup_result_directory()
        
    def setup_result_directory(self):
        """设置结果目录"""
        # 创建基础results目录
        if not os.path.exists('results'):
            os.makedirs('results')
            
        # 创建基于时间戳的子目录
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.result_dir = os.path.join('results', f'snkrdunk_{timestamp}')
        os.makedirs(self.result_dir)
        
        # 创建子目录
        self.pages_dir = os.path.join(self.result_dir, 'pages')
        self.models_dir = os.path.join(self.result_dir, 'models')
        os.makedirs(self.pages_dir)
        os.makedirs(self.models_dir)
        
        logger.info(f"结果将保存到: {self.result_dir}")
        
    def get_page(self, url, max_retries=3, timeout=15, retry_delay=2):
        """获取页面内容，带重试功能"""
        return self.make_request(url, max_retries, timeout, retry_delay)
    
    def make_request(self, url, max_retries=3, timeout=15, retry_delay=2):
        """执行HTTP请求，带重试功能
        
        Args:
            url: 请求URL
            max_retries: 最大重试次数
            timeout: 请求超时时间（秒）
            retry_delay: 重试间隔时间（秒）
        
        Returns:
            str: 页面内容，失败返回None
        """
        for attempt in range(max_retries + 1):
            try:
                if attempt == 0:
                    logger.info(f"正在请求: {url}")
                else:
                    logger.info(f"重试请求: {url} (第 {attempt} 次重试)")
                
                response = self.session.get(url, timeout=timeout)
                response.raise_for_status()
                
                # 请求成功，返回内容
                if attempt > 0:
                    logger.info(f"  请求成功 (重试 {attempt} 次后成功)")
                
                return response.text
                
            except requests.exceptions.Timeout as e:
                error_msg = f"请求超时: {e}"
                self._handle_request_error(url, attempt, max_retries, error_msg, retry_delay)
                
            except requests.exceptions.ConnectionError as e:
                error_msg = f"连接错误: {e}"
                self._handle_request_error(url, attempt, max_retries, error_msg, retry_delay)
                
            except requests.exceptions.HTTPError as e:
                error_msg = f"HTTP错误: {e}"
                if hasattr(e, 'response') and e.response.status_code == 429:  # 请求过于频繁
                    logger.info(f"  请求过于频繁，等待更长时间...")
                    time.sleep(retry_delay * 3)  # 429错误等待更长时间
                self._handle_request_error(url, attempt, max_retries, error_msg, retry_delay)
                
            except requests.exceptions.RequestException as e:
                error_msg = f"请求异常: {e}"
                self._handle_request_error(url, attempt, max_retries, error_msg, retry_delay)
                
            except Exception as e:
                error_msg = f"未知错误: {e}"
                self._handle_request_error(url, attempt, max_retries, error_msg, retry_delay)
        
        logger.info(f"请求最终失败: {url}")
        return None
    
    def _handle_request_error(self, url, attempt, max_retries, error_msg, retry_delay):
        """处理请求错误"""
        if attempt < max_retries:
            logger.error(f"  {error_msg}")
            logger.warning(f"  等待 {retry_delay} 秒后重试...")
            time.sleep(retry_delay)
        else:
            logger.error(f"  {error_msg}")
            logger.error(f"  已达到最大重试次数，放弃请求")
    
    def extract_brands_and_models(self, html_content):
        """从JavaScript数据中提取品牌和模型信息"""
        brands_data = []
        
        # 提取品牌数据
        brands_pattern = r':sidebar-brands="([^"]+)"'
        brands_match = re.search(brands_pattern, html_content)
        
        # 提取模型数据
        models_pattern = r':brand-id-models="([^"]+)"'
        models_match = re.search(models_pattern, html_content)
        
        if brands_match and models_match:
            try:
                # 解码HTML实体并解析JSON
                import html
                brands_json_str = html.unescape(brands_match.group(1))
                models_json_str = html.unescape(models_match.group(1))
                
                brands_json = json.loads(brands_json_str)
                models_json = json.loads(models_json_str)
                
                # 合并品牌和模型数据
                for brand in brands_json:
                    brand_id = brand.get('id', '')
                    brand_info = {
                        'id': brand_id,
                        'name': brand.get('name', ''),
                        'localized_name': brand.get('localizedName', ''),
                        'url': f"{self.base_url}/brands/{brand_id}",
                        'models': []
                    }
                    
                    # 添加该品牌下的所有模型
                    if brand_id in models_json:
                        for model in models_json[brand_id]:
                            model_info = {
                                'id': model.get('id', ''),
                                'name': model.get('name', ''),
                                'localized_name': model.get('localizedName', ''),
                                'brand_id': brand_id,
                                'brand_name': brand.get('name', ''),
                                'brand_localized_name': brand.get('localizedName', ''),
                                'url': f"{self.base_url}/products?brand={brand_id}&model={model.get('id', '')}",
                                'products_url': f"{self.base_url}/models/{model.get('id', '')}/products?order=release",
                                'products': [],
                                'page_files': []  # 记录页面文件路径
                            }
                            brand_info['models'].append(model_info)
                    
                    brands_data.append(brand_info)
                    
            except json.JSONDecodeError as e:
                logger.info(f"JSON解析失败: {e}")
                
        return brands_data
    
    def extract_main_categories(self, html_content):
        """提取主要分类导航"""
        categories = []
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 提取主导航分类
        nav = soup.find('nav', {'id': 'gnav-pc'})
        if nav:
            nav_items = nav.find_all('a')
            for item in nav_items:
                category_info = {
                    'name': item.get_text(strip=True),
                    'url': urljoin(self.base_url, item.get('href', ''))
                }
                categories.append(category_info)
        
        return categories
    
    def extract_products_from_page(self, html_content, page_url):
        """从商品列表页面提取商品信息"""
        products = []
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 查找商品列表 - 尝试多种可能的选择器
        product_items = soup.find_all('li', class_='item-list')
        
        if not product_items:
            # 如果没找到，尝试其他可能的选择器
            product_items = soup.find_all('li', {'class': lambda x: x and 'item' in ' '.join(x)})
        
        for i, item in enumerate(product_items):
            try:
                # 查找商品链接
                product_link = item.find('a', class_='item-block') or item.find('a')
                if not product_link:
                    continue
                
                # 提取商品名称
                product_name_elem = item.find('p', class_='item-name')
                product_name = product_name_elem.get_text(strip=True) if product_name_elem else '未知商品'
                
                # 提取价格信息
                price_elem = item.find('p', class_='item-price')
                price_text = ''
                if price_elem:
                    # 获取所有文本内容，包括子元素
                    price_text = price_elem.get_text(strip=True)
                
                # 提取出品和优惠信息
                sell_num_elem = item.find('p', class_='sell-num')
                sell_info = sell_num_elem.get_text(strip=True) if sell_num_elem else ''
                
                # 提取商品图片
                img_elem = item.find('img')
                img_url = ''
                if img_elem:
                    # 优先使用 data-src，然后是 src
                    img_url = img_elem.get('data-src') or img_elem.get('src') or ''
                    if img_url:
                        img_url = urljoin(self.base_url, img_url)
                
                # 提取商品详情链接
                product_href = product_link.get('href', '')
                product_detail_url = urljoin(self.base_url, product_href)
                
                # 解析价格
                price = ''
                if price_text:
                    price_match = re.search(r'¥([\d,]+)', price_text)
                    if price_match:
                        price = price_match.group(1).replace(',', '')
                
                # 解析出品和优惠数量
                sell_count = '0'
                offer_count = '0'
                
                if sell_info:
                    sell_match = re.search(r'出品(\d+\+?)', sell_info)
                    offer_match = re.search(r'オファー(\d+\+?)', sell_info)
                    
                    sell_count = sell_match.group(1) if sell_match else '0'
                    offer_count = offer_match.group(1) if offer_match else '0'
                
                # 判断商品状态
                status = 'unknown'
                if price_text:
                    if '出品待ち' in price_text or '出品0' in sell_info:
                        status = 'waiting'
                    elif '即購入可' in price_text:
                        status = 'available'
                    elif price:
                        status = 'available'
                    else:
                        status = 'waiting'
                
                product_info = {
                    'name': product_name,
                    'price': price,
                    'price_text': price_text,
                    'status': status,
                    'sell_count': sell_count,
                    'offer_count': offer_count,
                    'sell_info': sell_info,
                    'image_url': img_url,
                    'detail_url': product_detail_url,
                    'source_page': page_url,
                    'product_id': product_href.split('/')[-1] if product_href else ''
                }
                
                products.append(product_info)
                    
            except Exception as e:
                continue
        
        return products
    
    def extract_pagination_info(self, html_content):
        """提取分页信息"""
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 查找总数信息，如"全164件 1〜50件目"
        total_info = soup.find(string=re.compile(r'全\d+件'))
        total_count = 0
        if total_info:
            total_match = re.search(r'全(\d+)件', total_info)
            if total_match:
                total_count = int(total_match.group(1))
        
        # 只从分页链接中提取页码
        max_page = 1
        pagination_links = soup.find_all('a', href=re.compile(r'page=\d+'))
        for link in pagination_links:
            href = link.get('href', '')
            page_match = re.search(r'page=(\d+)', href)
            if page_match:
                page_num = int(page_match.group(1))
                max_page = max(max_page, page_num)
        
        # 没有分页链接就说明只有1页，不需要额外计算
        
        return {
            'total_count': total_count,
            'total_pages': max_page,
        }
    
    def save_page_data(self, model_id, page_number, products, page_url):
        """保存单页数据到文件"""
        page_filename = f"{model_id}_page_{page_number}.json"
        page_filepath = os.path.join(self.pages_dir, page_filename)
        
        page_data = {
            'model_id': model_id,
            'page_number': page_number,
            'page_url': page_url,
            'product_count': len(products),
            'products': products,
            'crawl_time': datetime.now().isoformat()
        }
        
        with open(page_filepath, 'w', encoding='utf-8') as f:
            json.dump(page_data, f, ensure_ascii=False, indent=2)
        
        return page_filepath
    
    def crawl_model_products(self, model_info):
        """爬取某个模型的所有商品"""
        model_id = model_info['id']
        products_url = model_info['products_url']
        
        logger.info(f"正在爬取模型 {model_info['name']} ({model_info['localized_name']}) 的商品...")
        
        # 获取第一页来获取分页信息
        first_page_html = self.get_page(products_url, max_retries=3, timeout=20, retry_delay=2)
        if not first_page_html:
            logger.error(f"无法获取模型 {model_id} 的商品页面")
            return []
        
        # 提取分页信息
        pagination_info = self.extract_pagination_info(first_page_html)
        total_pages = pagination_info['total_pages']
        total_count = pagination_info['total_count']
        
        logger.info(f"  模型 {model_id} 共有 {total_count} 个商品，{total_pages} 页")
        
        # 提取第一页的商品并保存
        first_page_products = self.extract_products_from_page(first_page_html, products_url)
        page_file_1 = self.save_page_data(model_id, 1, first_page_products, products_url)
        page_files = [page_file_1]
        
        # 打印第一页解析信息
        logger.info(f"  品牌: {model_info['brand_name']} ({model_info['brand_localized_name']}) | 模型: {model_info['name']} ({model_info['localized_name']}) | URL: {products_url} | 商品数: {len(first_page_products)}")
        
        all_products = first_page_products.copy()
        
        # 如果有多页，并发获取其他页面
        if total_pages > 1:
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = []
                
                for page in range(2, total_pages + 1):
                    page_url = f"{products_url}&page={page}"
                    future = executor.submit(self.crawl_single_page, model_info, page_url, page)
                    futures.append((future, page))
                
                # 收集所有页面的商品
                for future, page_num in futures:
                    try:
                        page_products, page_file = future.result(timeout=30)
                        if page_products:
                            all_products.extend(page_products)
                            page_files.append(page_file)
                    except Exception as e:
                        logger.info(f"获取第 {page_num} 页失败: {e}")
        
        # 更新模型信息
        model_info['page_files'] = page_files
        
        logger.info(f"  模型 {model_id} 实际获取到 {len(all_products)} 个商品，保存了 {len(page_files)} 个页面文件")
        return all_products
    
    def crawl_single_page(self, model_info, page_url, page_number):
        """爬取单个页面的商品"""
        html_content = self.get_page(page_url, max_retries=2, timeout=20, retry_delay=3)
        if html_content:
            products = self.extract_products_from_page(html_content, page_url)
            page_file = self.save_page_data(model_info['id'], page_number, products, page_url)
            
            # 打印页面解析信息
            logger.info(f"    品牌: {model_info['brand_name']} ({model_info['brand_localized_name']}) | 模型: {model_info['name']} ({model_info['localized_name']}) | 页面: {page_number} | URL: {page_url} | 商品数: {len(products)}")
            
            return products, page_file
        return [], None
    
    def save_model_summary(self, model_info):
        """保存模型汇总信息"""
        model_filename = f"{model_info['id']}_summary.json"
        model_filepath = os.path.join(self.models_dir, model_filename)
        
        # 创建模型汇总数据（不包含products，只包含统计信息）
        model_summary = {
            'id': model_info['id'],
            'name': model_info['name'],
            'localized_name': model_info['localized_name'],
            'url': model_info['url'],
            'products_url': model_info['products_url'],
            'total_products': len(model_info.get('products', [])),
            'page_files': model_info.get('page_files', []),
            'crawl_time': datetime.now().isoformat()
        }
        
        with open(model_filepath, 'w', encoding='utf-8') as f:
            json.dump(model_summary, f, ensure_ascii=False, indent=2)
        
        return model_filepath
    
    def consolidate_data(self, brands_data):
        """汇总所有数据"""
        logger.info("\n开始汇总数据...")
        
        # 读取所有页面文件并汇总
        all_page_files = glob.glob(os.path.join(self.pages_dir, "*.json"))
        
        all_products = []
        brand_stats = {}
        model_stats = {}
        total_products = 0
        
        # 处理每个品牌
        for brand in brands_data:
            brand_id = brand['id']
            brand_name = brand['name']
            brand_localized_name = brand['localized_name']
            brand_product_count = 0
            
            # 处理每个模型
            for model in brand['models']:
                model_id = model['id']
                model_name = model['name']
                model_localized_name = model['localized_name']
                
                # 保存模型汇总
                model_summary_file = self.save_model_summary(model)
                
                # 汇总该模型的所有商品
                model_products = []
                for page_file in model.get('page_files', []):
                    if os.path.exists(page_file):
                        with open(page_file, 'r', encoding='utf-8') as f:
                            page_data = json.load(f)
                            model_products.extend(page_data['products'])
                
                # 为每个商品添加品牌和模型信息
                for product in model_products:
                    product_with_context = {
                        'brand_id': brand_id,
                        'brand_name': brand_name,
                        'brand_localized_name': brand_localized_name,
                        'model_id': model_id,
                        'model_name': model_name,
                        'model_localized_name': model_localized_name,
                        **product  # 包含原有的商品信息
                    }
                    all_products.append(product_with_context)
                
                # 更新统计信息
                model_product_count = len(model_products)
                model_stats[f"{brand_name}/{model_name}"] = {
                    'brand_id': brand_id,
                    'brand_name': brand_name,
                    'brand_localized_name': brand_localized_name,
                    'model_id': model_id,
                    'model_name': model_name,
                    'model_localized_name': model_localized_name,
                    'product_count': model_product_count,
                    'page_files_count': len(model.get('page_files', []))
                }
                
                brand_product_count += model_product_count
                total_products += model_product_count
            
            # 品牌统计
            brand_stats[brand_name] = {
                'id': brand_id,
                'name': brand_name,
                'localized_name': brand_localized_name,
                'model_count': len(brand['models']),
                'product_count': brand_product_count
            }
        
        # 生成products.json
        products_file = os.path.join(self.result_dir, 'products.json')
        with open(products_file, 'w', encoding='utf-8') as f:
            json.dump(all_products, f, ensure_ascii=False, indent=2)
        
        # 生成categories.json（分类数据）
        categories_data = {
            'crawl_time': datetime.now().isoformat(),
            'total_brands': len(brands_data),
            'total_models': sum(len(brand['models']) for brand in brands_data),
            'brands': []
        }
        
        for brand in brands_data:
            brand_info = {
                'id': brand['id'],
                'name': brand['name'],
                'localized_name': brand['localized_name'],
                'url': brand['url'],
                'models': []
            }
            
            for model in brand['models']:
                model_info = {
                    'id': model['id'],
                    'name': model['name'],
                    'localized_name': model['localized_name'],
                    'url': model['url'],
                    'products_url': model['products_url']
                }
                brand_info['models'].append(model_info)
            
            categories_data['brands'].append(brand_info)
        
        categories_file = os.path.join(self.result_dir, 'categories.json')
        with open(categories_file, 'w', encoding='utf-8') as f:
            json.dump(categories_data, f, ensure_ascii=False, indent=2)
        
        # 生成summary.json
        summary_data = {
            'total_statistics': {
                'total_brands': len(brands_data),
                'total_models': sum(len(brand['models']) for brand in brands_data),
                'total_products': total_products,
                'total_page_files': len(all_page_files),
                'crawl_time': datetime.now().isoformat()
            },
            'brand_statistics': brand_stats,
            'model_statistics': model_stats,
            'top_brands_by_products': sorted(
                [(name, stats['product_count']) for name, stats in brand_stats.items()],
                key=lambda x: x[1], reverse=True
            )[:10],
            'top_models_by_products': sorted(
                [(name, stats['product_count']) for name, stats in model_stats.items()],
                key=lambda x: x[1], reverse=True
            )[:20]
        }
        
        summary_file = os.path.join(self.result_dir, 'summary.json')
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"products.json 已保存: {products_file}")
        logger.info(f"categories.json 已保存: {categories_file}")
        logger.info(f"summary.json 已保存: {summary_file}")
        logger.info(f"总计: {total_products} 个商品，分布在 {len(all_page_files)} 个页面文件中")
        
        # 输出统计信息
        logger.info(f"\n=== 汇总统计信息 ===")
        logger.info(f"品牌数量: {len(brand_stats)}")
        logger.info(f"模型数量: {len(model_stats)}")
        logger.info(f"商品总数: {total_products}")
        
        if brand_stats:
            logger.info(f"\n商品数量最多的前5个品牌:")
            for brand_name, product_count in summary_data['top_brands_by_products'][:5]:
                logger.info(f"  {brand_name}: {product_count} 个商品")
        
        if model_stats:
            logger.info(f"\n商品数量最多的前5个模型:")
            for model_name, product_count in summary_data['top_models_by_products'][:5]:
                logger.info(f"  {model_name}: {product_count} 个商品")
        
        return {
            'products': all_products,
            'categories': categories_data,
            'summary': summary_data
        }
    
    def crawl_all_products(self, brands_data, max_models_per_brand=None, max_concurrent_models=5):
        """爬取所有商品信息"""
        logger.info("开始爬取所有商品信息...")
        
        total_models = 0
        for brand in brands_data:
            total_models += len(brand['models'])
        
        logger.info(f"总共需要爬取 {len(brands_data)} 个品牌的 {total_models} 个模型")
        
        if max_models_per_brand:
            logger.info(f"限制每个品牌最多爬取 {max_models_per_brand} 个模型")
        
        logger.info(f"使用 {max_concurrent_models} 个并发线程处理模型")
        
        for brand_idx, brand in enumerate(brands_data):
            logger.info(f"\n处理品牌 {brand_idx + 1}/{len(brands_data)}: {brand['name']} ({brand['localized_name']})")
            
            models_to_process = brand['models']
            if max_models_per_brand:
                models_to_process = models_to_process[:max_models_per_brand]
            
            logger.info(f"  准备并发处理 {len(models_to_process)} 个模型...")
            
            # 使用线程池并发处理模型
            with ThreadPoolExecutor(max_workers=max_concurrent_models) as executor:
                future_to_model = {}
                
                # 提交所有模型的爬取任务
                for model_idx, model in enumerate(models_to_process):
                    future = executor.submit(self.crawl_model_with_error_handling, model, model_idx + 1, len(models_to_process))
                    future_to_model[future] = model
                
                # 收集结果
                completed_count = 0
                for future in future_to_model:
                    try:
                        model = future_to_model[future]
                        products, product_count, page_files = future.result(timeout=300)  # 5分钟超时
                        
                        model['products'] = products
                        model['product_count'] = product_count
                        model['page_files'] = page_files if page_files else []
                        
                        completed_count += 1
                        logger.info(f"  完成模型 {completed_count}/{len(models_to_process)}: {model['name']}")
                        
                    except Exception as e:
                        model = future_to_model[future]
                        logger.info(f"  模型 {model['name']} 处理失败: {e}")
                        model['products'] = []
                        model['product_count'] = 0
                        model['page_files'] = []
                        completed_count += 1
            
            logger.info(f"  品牌 {brand['name']} 处理完成")
            # 品牌之间添加短暂延时
            time.sleep(1)
        
        return brands_data
    
    def crawl_model_with_error_handling(self, model, model_idx, total_models):
        """带错误处理的模型爬取"""
        try:
            with self.lock:
                logger.info(f"    开始处理模型 {model_idx}/{total_models}: {model['name']} ({model['localized_name']})")
            
            products = self.crawl_model_products(model)
            page_files = model.get('page_files', [])
            
            with self.lock:
                logger.info(f"    模型 {model['name']} 处理完成: {len(products)} 个商品")
            
            return products, len(products), page_files
            
        except Exception as e:
            with self.lock:
                logger.info(f"    模型 {model['name']} 处理失败: {e}")
            return [], 0, []
    
    def parse_category_page(self, url):
        """解析分类页面"""
        logger.info(f"正在解析分类页面: {url}")
        
        html_content = self.get_page(url, max_retries=3, timeout=20, retry_delay=2)
        if not html_content:
            logger.info(f"无法获取分类页面: {url}")
            return None
        
        # 提取品牌和模型数据
        brands_data = self.extract_brands_and_models(html_content)
        main_categories = self.extract_main_categories(html_content)
        
        result = {
            'url': url,
            'main_categories': main_categories,
            'brands': brands_data
        }
        
        return result
    
    def save_to_file(self, data, filename):
        """保存数据到文件"""
        filepath = os.path.join(self.result_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"数据已保存到 {filepath}")
    
    def get_summary_stats(self, brands_data):
        """获取统计信息"""
        total_brands = len(brands_data)
        total_models = sum(len(brand['models']) for brand in brands_data)
        total_products = sum(
            sum(len(model.get('products', [])) for model in brand['models'])
            for brand in brands_data
        )
        
        return {
            'total_brands': total_brands,
            'total_models': total_models,
            'total_products': total_products
        }
    
    def run(self, crawl_products=True, max_models_per_brand=None, specific_category=None):
        """运行爬虫"""
        all_category_urls = {
            'sneaker': 'https://snkrdunk.com/departments/sneaker',
            'apparel': 'https://snkrdunk.com/departments/apparel',
            'hobby': 'https://snkrdunk.com/departments/hobby',
            'luxury': 'https://snkrdunk.com/departments/luxury'
        }
        
        if specific_category:
            if specific_category in all_category_urls:
                category_urls = [all_category_urls[specific_category]]
                logger.info(f"只爬取 {specific_category} 分类")
            else:
                logger.info(f"无效的分类: {specific_category}，爬取所有分类")
                category_urls = list(all_category_urls.values())
        else:
            category_urls = list(all_category_urls.values())
        
        all_data = []
        
        for url in category_urls:
            result = self.parse_category_page(url)
            if result:
                # 如果需要爬取商品信息
                if crawl_products:
                    # 根据模型数量调整并发数
                    max_concurrent = 2 if max_models_per_brand and max_models_per_brand <= 3 else 3
                    result['brands'] = self.crawl_all_products(result['brands'], max_models_per_brand, max_concurrent)
                    
                    # 汇总数据
                    self.consolidate_data(result['brands'])
                
                all_data.append(result)
                
                # 输出统计信息
                stats = self.get_summary_stats(result['brands'])
                logger.info(f"\n=== 分类信息统计 ===")
                logger.info(f"主要分类数量: {len(result['main_categories'])}")
                logger.info(f"品牌数量: {stats['total_brands']}")
                logger.info(f"总模型数量: {stats['total_models']}")
                if crawl_products:
                    logger.info(f"总商品数量: {stats['total_products']}")
                
                # 输出主要分类
                if result['main_categories']:
                    logger.info(f"\n主要分类:")
                    for category in result['main_categories']:
                        logger.info(f"  - {category['name']}")
                
                # 输出前5个品牌及其模型和商品数量
                if result['brands']:
                    logger.info(f"\n前5个品牌:")
                    for i, brand in enumerate(result['brands'][:5]):
                        brand_product_count = sum(len(model.get('products', [])) for model in brand['models'])
                        logger.info(f"  {i+1}. {brand['name']} ({brand['localized_name']}) - {len(brand['models'])} 个模型")
                        if crawl_products:
                            logger.info(f"     总商品数: {brand_product_count}")
                
                # 输出某个模型的商品示例
                if crawl_products and result['brands'] and result['brands'][0]['models']:
                    first_brand = result['brands'][0]
                    for model in first_brand['models']:
                        if model.get('products'):
                            logger.info(f"\n{first_brand['name']} - {model['name']} 的前3个商品:")
                            for i, product in enumerate(model['products'][:3]):
                                logger.info(f"    {i+1}. {product['name']} - {product['price_text']}")
                            break
        
        # 保存原始数据（用于备份）
        if all_data:
            filename = 'raw_data.json'
            self.save_to_file(all_data, filename)
        
        logger.info(f"\n所有文件已保存到目录: {self.result_dir}")
        return all_data

if __name__ == "__main__":
    spider = SnkrDunkSpider()
    
    # 选择运行模式
    logger.info("选择运行模式:")
    logger.info("1. 只爬取分类信息（快速）")
    logger.info("2. 爬取所有商品（包含所有分类，较慢）")
    logger.info("3. 只爬取 sneaker 分类商品")
    logger.info("4. 只爬取 apparel 分类商品") 
    logger.info("5. 只爬取 hobby 分类商品")
    logger.info("6. 只爬取 luxury 分类商品")
    
    choice = input("请输入选择 (1/2/3/4/5/6): ").strip()
    
    if choice == "1":
        spider.run(crawl_products=False)
    elif choice == "2":
        spider.run(crawl_products=True)
    elif choice == "3":
        spider.run(crawl_products=True, specific_category='sneaker')
    elif choice == "4":
        spider.run(crawl_products=True, specific_category='apparel')
    elif choice == "5":
        spider.run(crawl_products=True, specific_category='hobby')
    elif choice == "6":
        spider.run(crawl_products=True, specific_category='luxury')
    else:
        logger.info("无效选择，使用默认模式（只爬取分类信息）")
        spider.run(crawl_products=False)