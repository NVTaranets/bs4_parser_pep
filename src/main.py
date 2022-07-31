import logging
import re
from collections import defaultdict
from urllib.parse import urljoin

import requests_cache
from bs4 import BeautifulSoup
from tqdm import tqdm

from configs import configure_argument_parser, configure_logging
from constants import (BASE_DIR, DOWNLOAD_URL, EXPECTED_STATUS, MAIN_DOC_URL,
                       MAIN_PEP_URL, WHATS_NEW_URL)
from outputs import control_output
from utils import find_tag, get_response


def whats_new(session):

    response = get_response(session, WHATS_NEW_URL)
    if response is None:
        return response

    soup = BeautifulSoup(response.text, features='lxml')
    main_div = find_tag(soup, 'section', attrs={'id': 'what-s-new-in-python'})
    div_with_ul = find_tag(main_div, 'div', attrs={'class': 'toctree-wrapper'})
    sections_by_python = div_with_ul.find_all(
        'li',
        attrs={'class': 'toctree-l1'}
        )

    results = [('Ссылка на статью', 'Заголовок', 'Редактор, Автор')]
    for section in tqdm(sections_by_python):
        version_a_tag = find_tag(section, 'a')
        href = version_a_tag['href']
        version_link = urljoin(WHATS_NEW_URL, href)
        response = get_response(session, version_link)
        if response is None:
            continue
        soup = BeautifulSoup(response.text, features='lxml')
        h1 = find_tag(soup, 'h1')
        dl = find_tag(soup, 'dl')
        dl_text = dl.text.replace('\n', ' ')
        results.append(
            (version_link, h1.text, dl_text)
        )
    return results


def latest_versions(session):

    response = get_response(session, MAIN_DOC_URL)
    if response is None:
        return response
    soup = BeautifulSoup(response.text, 'lxml')
    sidebar = find_tag(soup, 'div', {'class': 'sphinxsidebarwrapper'})
    ul_tags = sidebar.find_all('ul')
    for ul in ul_tags:
        if 'All versions' in ul.text:
            a_tags = ul.find_all('a')
            break
    else:
        raise Exception('Ничего не нашлось')
    results = [('Ссылка на документацию', 'Версия', 'Статус')]
    pattern = r'Python (?P<version>\d\.\d+) \((?P<status>.*)\)'
    for a_tag in a_tags:
        link = a_tag['href']
        text_match = re.search(pattern, a_tag.text)
        if text_match is not None:
            version, status = text_match.groups()
        else:
            version, status = a_tag.text, ''
        results.append(
            (link, version, status)
        )

    return results


def download(session):

    response = get_response(session, DOWNLOAD_URL)
    if response is None:
        return
    soup = BeautifulSoup(response.text, features='lxml')
    main_tag = find_tag(soup, 'div', {'role': 'main'})
    table_tag = find_tag(main_tag, 'table', {'class': 'docutils'})
    pdf_a4_tag = find_tag(
        table_tag,
        'a',
        {'href': re.compile(r'.+pdf-a4\.zip$')}
        )
    pdf_a4_link = pdf_a4_tag['href']
    archive_url = urljoin(DOWNLOAD_URL, pdf_a4_link)
    filename = archive_url.split('/')[-1]
    downloads_dir = BASE_DIR / 'downloads'
    downloads_dir.mkdir(exist_ok=True)
    archive_path = downloads_dir / filename
    response = session.get(archive_url)
    with open(archive_path, 'wb') as file:
        file.write(response.content)
    logging.info(f'Архив был загружен и сохранён: {archive_path}')


def pep(session):

    response = get_response(session, MAIN_PEP_URL)
    if response is None:
        return response

    soup = BeautifulSoup(response.text, features='lxml')
    numerical_index = find_tag(
        soup,
        "section",
        attrs={'id': 'numerical-index'}
    )

    hrefs = []
    tbody = find_tag(numerical_index, 'tbody')
    pep_tr_tags = tbody.find_all('tr')
    for pep_tr_tag in pep_tr_tags:
        status_pep = pep_tr_tag.text.split('\n')[0][1:]
        pep_td_tag = find_tag(
            pep_tr_tag,
            "a",
            attrs={'class': 'pep reference internal'}
        )
        hrefs.append(
            (status_pep, pep_td_tag['href'], pep_td_tag['title'])
        )

    not_exist_err_status = True
    counts = defaultdict(int)
    for pep in tqdm(hrefs):

        status_pep, href, name = pep

        pep_link = urljoin(MAIN_PEP_URL, href)
        response = get_response(session, pep_link)
        if response is None:
            continue

        soup = BeautifulSoup(response.text, features='lxml')
        dl = find_tag(soup, 'dl', attrs={'class': 'rfc2822 field-list simple'})
        status_tag = find_tag(dl, '', string='Status').parent
        status = status_tag.find_next_sibling().string
        expected_status = EXPECTED_STATUS[status_pep]

        if not (status in expected_status):
            info_msg = [
                'Несовпадающие статусы:' if not_exist_err_status else '',
                pep_link,
                f'Статус в карточке:{status}',
                (f'Ожидаемые статусы: {expected_status}'
                 if len(expected_status) < 1
                 else f'Ожидаемый статус: {expected_status[0]}'
                 ),
            ]
            logging.info('\r\n'.join(info_msg))
            not_exist_err_status = False
        counts[status] += 1

    return (
        [('Статус', 'Количество')]
        + [(key, counts[key]) for key in counts]
        + [('Total', len(hrefs))]
    )


MODE_TO_FUNCTION = {
    'whats-new': whats_new,
    'latest-versions': latest_versions,
    'download': download,
    'pep': pep,
}


def main():
    configure_logging()
    logging.info('Парсер запущен!')

    arg_parser = configure_argument_parser(MODE_TO_FUNCTION.keys())
    args = arg_parser.parse_args()
    logging.info(f'Аргументы командной строки: {args}')

    session = requests_cache.CachedSession()
    if args.clear_cache:
        session.cache.clear()
    parser_mode = args.mode
    results = MODE_TO_FUNCTION[parser_mode](session)
    if results is not None:
        control_output(results, args)
    logging.info('Парсер завершил работу.')


if __name__ == '__main__':
    main()
