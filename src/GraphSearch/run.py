import json
import os
from argparse import ArgumentParser
import pandas as pd
import time
import numpy as np
import torch
from torch.utils.data import DataLoader
from torch import nn

from common.data_preparation import parser_add_data_arguments, data_preparation
from common.metrics import display
from common.experiment import *
from .AmazonDataset import AmazonDataset
from .Model import Model
from .evaluate import evaluate


# if __name__ == '__main__':
def run():
    torch.backends.cudnn.enabled = True
    parser = ArgumentParser()
    parser_add_data_arguments(parser)
    # ------------------------------------Experiment Setup------------------------------------
    parser.add_argument('--lr',
                        default=0.1,
                        help='learning rate for fast adaptation')
    parser.add_argument('--batch_size',
                        default=256,
                        type=int,
                        help='batch size for training')
    parser.add_argument('--neg_sample_num',
                        default=5,
                        type=int,
                        help='negative sample number')
    parser.add_argument('--mode',
                        default='ordinary',
                        choices=('ordinary', 'no_text_prop', 'no_id_prop'),
                        type=str,
                        help='experiment setup')
    # ------------------------------------Model Hyper Parameters------------------------------------
    parser.add_argument('--embedding_size',
                        default=64,
                        type=int,
                        help="word embedding size")
    parser.add_argument('--word_embedding_size',
                        default=64,
                        type=int,
                        help="word embedding size")
    parser.add_argument('--entity_embedding_size',
                        default=64,
                        type=int,
                        help="entity embedding size")
    parser.add_argument('--head_num',
                        default=4,
                        type=int,
                        help='the number of heads used in multi head self-attention layer')
    parser.add_argument('--convolution_num',
                        default=4,
                        type=int,
                        help='the number of convolution layers')
    parser.add_argument('--regularization',
                        default=0.001,
                        type=float,
                        help='regularization factor')

    # ------------------------------------Data Preparation------------------------------------
    config = parser.parse_args()

    # -----------Caution!!! For convenience of training-----------
    if config.embedding_size != 0:
        config.word_embedding_size = config.embedding_size
        config.entity_embedding_size = config.embedding_size
    # ------------------------------------------------------------

    os.environ["CUDA_VISIBLE_DEVICES"] = config.device
    train_df, test_df, full_df, query_dict, asin_dict, word_dict = data_preparation(config)
    try:
        word2vec = torch.load(os.path.join(config.processed_path, '{}_word_matrix.pt'.format(config.dataset)))
    except FileNotFoundError:
        word2vec = None

    # clip words
    AmazonDataset.clip_words(full_df)
    users, item_map, query_map, graph = AmazonDataset.construct_graph(full_df, len(word_dict) + 1)
    # graph = graph.to('cuda:{}'.format(config.device))
    graph = graph.to('cuda')

    model = Model(graph, len(word_dict) + 1, len(query_map), len(users) + len(item_map),
                  word_embedding_size=config.word_embedding_size,
                  entity_embedding_size=config.entity_embedding_size,
                  head_num=config.head_num,
                  convolution_num=config.convolution_num,
                  l2=config.regularization)
    model.apply_word2vec(word2vec)
    model = model.cuda()
    model.init_graph()
    if config.load:
        model.load_state_dict(torch.load(config.save_path))
        model.graph_propagation()
        user_embeddings: torch.Tensor = model.graph.nodes['entity'].data['e'][:len(users), :model.entity_embedding_size]
        # top_similarities, top_words = word_similarity(config, word_dict, model)
        neighbor_similarity(config, user_embeddings)

        # user_b: torch.Tensor = model.graph.nodes['entity'].data['e'][:len(users), model.entity_embedding_size:]
        # word_embeddings = model.word_embedding_layer.weight
        # top_words = word_similarity(word_embeddings, user_b, word_dict)
        # word_dict: dict = word_dict
        # reversed_word_dict = {v: k for k, v in word_dict.items()}
        # for word in top_words[0]:
        #     print(reversed_word_dict[word.item()], end=' ')
        return

    train_dataset = AmazonDataset(train_df, users, item_map, asin_dict, neg_sample_num=config.neg_sample_num)
    test_dataset = AmazonDataset(test_df, users, item_map, asin_dict)

    train_loader = DataLoader(train_dataset, drop_last=True, batch_size=config.batch_size, shuffle=True, num_workers=0,
                              collate_fn=AmazonDataset.collate_fn)
    test_loader = DataLoader(test_dataset, drop_last=True, batch_size=1, shuffle=False, num_workers=0)

    # criterion = nn.TripletMarginLoss(margin=config.margin, reduction='mean')
    optimizer = torch.optim.Adagrad(model.parameters(), lr=config.lr)
    # ------------------------------------Train------------------------------------
    loss = 0
    # Mrr, Hr, Ndcg = metrics(model, test_dataset, test_loader, 10)

    for epoch in range(config.epochs):
        start_time = time.time()
        model.train()
        for _, (users, items, neg_items, query_words) in enumerate(train_loader):
            # pred, pos, neg = model(users, items, query_words, 'train', negs)
            # loss = criterion(pred, pos, neg)
            loss = model(users, items, query_words, 'train', neg_items)
            # print("loss:{:.3f}".format(float(loss)))

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

        Mrr, Hr, Ndcg = evaluate(model, test_dataset, test_loader, 10)
        display(epoch, config.epochs, loss, Hr, Mrr, Ndcg, start_time)

    if not config.load:
        torch.save(model.state_dict(), config.save_path)


def user_similarity(model: Model, user_num):
    user: torch.Tensor = model.graph.nodes['entity'].data['e'][:user_num, :model.entity_embedding_size]
    user_t = user.transpose(0, 1)
    prob = torch.sigmoid(user @ user_t)
    _, top_k_similar_users = torch.topk(prob, 5, dim=-1)
