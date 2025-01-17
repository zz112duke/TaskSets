from itertools import combinations
import matplotlib.pyplot as plt
import numpy as np
import os
import pandas as pd
import theano.tensor as T

from theano.tensor.shared_randomstreams import RandomStreams
rs = RandomStreams()


# Initial Q-value for actions and TS
def get_alien_initial_q(model_name):
    if model_name == 'Bayes':
        return 1 / 3
    else:
        return 1.2


def get_alien_paths():

    base_path = 'C:/Users/maria/MEGAsync/Berkeley/TaskSets'
    return {
        'human data': base_path + '/Data/version3.1/',  # '/Data/versions1.0and3.1/'
        'human data prepr': base_path + '/Data/version3.1preprocessed/',  # '/Data/versions1.0and3.1preprocessed',
        'fitting results': base_path + '/models',
        # 'fitting results': base_path + '/AliensFitting/',
        # 'simulations': 'C:/Users/maria/MEGAsync/SLCN/PSsimulations/'
    }


# Same, but without theano, and selecting actions rather than reading them in from a file
def update_Qs_sim(season, alien,
                  Q_low, Q_high,
                  beta, beta_high, alpha, alpha_high, forget, forget_high,
                  n_subj, n_actions, n_TS, task, alien_initial_Q,
                  model_name, action=[], verbose=False):

    # Select TS
    
    ### At each trial, the agent must select one TS to begin with. The first trial will use the high level Q values that are initialized as the expected value ###
    ### of each TS. And the following trials will use the Q from last trial's update. Send these Q values into a softmax function to select a TS. These Q vals ###
    ### for the current selected TS (hier RL; for Bayes RL, it'll be all TSs) will get updated after evaluating the action value of the current trial. ###
    Q_high_sub = Q_high[np.arange(n_subj), season]  # Q_high_sub.shape -> (n_subj, n_TS)
    p_high = softmax(beta_high * Q_high_sub, axis=1)   # p_high.shape -> (n_subj, n_TS)
    if model_name == 'flat':
        TS = season
    elif model_name == 'fs':
        TS = 0
    elif model_name == 'hier_det':
        TS = Q_high_sub.argmax(axis=1)
    elif (model_name == 'hier') or (model_name == 'Bayes'):
        TS = np.array([np.random.choice(a=n_TS, p=p_high_subj) for p_high_subj in p_high])

    # Select action
    
    ### At each trial, the agent must select one action. The first trial will use the low level Q values that are initialized as the expected value ###
    ### of each action. And the following trials will use the Q from last trial's update. Send these Q values into a softmax function to select an action. ###
    Q_low_sub = Q_low[np.arange(n_subj), TS, alien]  # Q_low_sub.shape -> [n_subj, n_actions]
    p_low = softmax(beta * Q_low_sub, axis=1)
    
    ### Look at the actual reward you got based on the selected action by calling task.produce_reward(action). ###
    if len(action) == 0:  # action can be provided as participant-chosen actions when calculating human values
        action = np.array([np.random.choice(a=n_actions, p=p_low_subj) for p_low_subj in p_low])
    reward, correct = task.produce_reward(action)

    # Forget Q-values a little bit
    Q_low = (1 - forget) * Q_low + forget * alien_initial_Q  # Q_low.shape -> [n_subj, n_TS, n_aliens, n_actions]
    Q_high = (1 - forget_high) * Q_high + forget_high * alien_initial_Q

    # Update low-level Q-values
    ### Now, after getting the actual reward from the current action selection and updating the Q value for the current action with forgetting param ###
    ### we can further update Q value for the current action with RPE, learning rate (alpha) and stochastic param (beta). ###
    current_trial_low = np.arange(n_subj), TS, alien, action # Find the current Q_low (action value) after the "forgetting" updates for the next update.
    if model_name == 'Bayes': #Bayes tests reliability
        RPE_low = correct - Q_low[current_trial_low]
    else:
        RPE_low = reward - Q_low[current_trial_low]
    
    ### After calculating RPE, we can use the learning rate alpha to update the current action value Q_low. ###
    Q_low[current_trial_low] += alpha * RPE_low

    
    # Update high-level Q-values
    
    ### After updating the current action value, we can update the high level Q values (Q_high). ###
    current_trial_high = np.arange(n_subj), season, TS
    if model_name == 'Bayes':  # update all TS; paper line 604-609
        p_r_given_TS_s_a = Q_low.transpose([0, 2, 3, 1])[np.arange(n_subj), alien, action] #[=Q(a|TS,s)]
        Q_high[np.arange(n_subj), season] *= p_r_given_TS_s_a  # P(TS|C) *= P(r|TS,s,a) [=Q(a|TS,s)]
        Q_high[np.arange(n_subj), season] /= np.sum(Q_high[np.arange(n_subj), season], axis=1, keepdims=True) #summing up all TS vals in a given context.
    else: #update only the current TS
        RPE_high = reward - Q_high[current_trial_high]
        Q_high[current_trial_high] += alpha_high * RPE_high

    if verbose:
        print("Q_high_sub:\n", Q_high_sub.round(3))
        print("p_high:\n", p_high.round(3))
        print("TS:", TS)
        print("Q_low_sub:\n", Q_low_sub.round(3))
        print("p_low:\n", p_low.round(3))
        print("action:", action)
        print("reward:", reward)
        print("correct:", correct)
        print("RPE_low:", RPE_low.round(3))
        # print("RPE_high:", RPE_high.round(3))
        print("new Q_high_sub:\n", Q_high[np.arange(n_subj), season].round(3))
        print("new Q_low_sub:\n", Q_low[np.arange(n_subj), TS, alien].round(3))

    return [Q_low, Q_high, TS, action, correct, reward, p_low]


def simulate_competition_phase(model_name, final_Q_high, final_Q_low, task,
                               n_seasons, n_aliens, n_sim, beta_high, n_blocks_comp=3):

    comp_data = pd.DataFrame(np.full((1, 4), np.nan),
                             columns=['perc_selected_better', 'se', 'choice', 'phase'])

    # Select between two seasons
    if (model_name == 'hier') or (model_name == 'Bayes'):
        Q_season = np.max(final_Q_high, axis=2)  # [n_sim, n_seasons] (value of highest-valued TS for each season)
    elif model_name == 'flat':
        Q_alien_corr_action = np.max(final_Q_low, axis=3)  # [n_sim, n_seasons, n_aliens] (alien values if correct action)
        Q_season = np.mean(Q_alien_corr_action, axis=2)  # [n_sim, n_seasons] (average over aliens in each season)
    else:
        raise ValueError("model_name must be 'hier', 'Bayes', or 'flat'.")

    for i, season_pair in enumerate(combinations(range(n_seasons), 2)):

        # Let agents choose (using softmax)
        p_season = softmax(beta_high * Q_season[:, season_pair], axis=1)  # prob. of selecting each season in the pair
        season_choice = np.array([np.random.choice(a=season_pair, size=n_blocks_comp, p=sim_p) for sim_p in p_season])

        # Calculate stats
        selected_better_sim = np.mean(season_choice == min(season_pair), axis=1)
        # selected_better_sim = p_season[:, 0]  # prob. of choosing lower-numbered [=0-indexed] TS
        selected_better_mean, selected_better_se = np.mean(selected_better_sim), np.std(selected_better_sim) / np.sqrt(len(selected_better_sim))
        comp_data.loc[i] = [selected_better_mean, selected_better_se, str(season_pair), 'season']

    # Select between aliens (same season)
    p_TS = softmax(beta_high.reshape(n_sim, 1, 1) * final_Q_high, axis=2)  # [n_sim, n_seasons, n_TS] (prob. of each TS in each season)
    Q_alien = np.max(final_Q_low, axis=3)  # [n_sim, n_TS, n_aliens] (alien values for most-rewarded actions)

    for season in range(n_seasons):
        for alien_pair in combinations(range(n_aliens), 2):

            # True alien values
            true_Q_aliens = np.max(task.TS[season], axis=1)[list(alien_pair)]
            if true_Q_aliens[0] != true_Q_aliens[1]:  # exclude aliens with identical values

                # Select TS
                if (model_name == 'hier') or (model_name == 'Bayes'):
                    selected_TS = [np.random.choice(a=range(n_seasons), p=p_sim) for p_sim in
                                   p_TS[:, season]]  # [n_sim] (TS selected by each sim)
                elif model_name == 'flat':
                    selected_TS = season * np.ones(n_sim, dtype=int)

                # Choose alien based on agent's learned alien values
                Q_aliens = np.array([Q_alien[np.arange(n_sim), selected_TS, alien] for alien in alien_pair]).T  # [n_sim, n_presented_aliens]
                p_aliens = softmax(Q_aliens, axis=1)
                alien_choice = np.array([np.random.choice(a=alien_pair, size=n_blocks_comp, p=sim_p) for sim_p in p_aliens])

                # Calculate stats
                better_alien = alien_pair[np.argmax(true_Q_aliens)]
                selected_better_sim = np.mean(alien_choice == better_alien, axis=1)
                # selected_better_sim = p_aliens[:, 0]
                selected_better_mean, selected_better_se = np.mean(selected_better_sim), np.std(selected_better_sim) / np.sqrt(len(selected_better_sim))
                comp_data.loc[i+1] = [selected_better_mean, selected_better_se, str(season) + str(alien_pair), 'season-alien']
                i += 1

    return comp_data


def simulate_rainbow_phase(n_seasons, model_name, n_sim,
                           beta, beta_high, final_Q_low, final_Q_high):

    if (model_name == 'hier') or (model_name == 'Bayes'):
        # Hierarchical agents first select a TS, then an action within this TS, according to the seen alien.
        # TS are selected by comparing their maximum values, i.e., the values in the season in which they are correct
        # Actions are selected like in the initial learning phase, i.e., by comparing the values of the different
        # actions, given the alien. TS and actions are selected using softmax (rather than, e.g., max).

        # Calculate p(TS) <- max(Q(TS))
        Q_TS = np.max(final_Q_high, axis=1)  # [n_sim, TS] Find the correct TS in each season.
        p_TS = softmax(beta_high * Q_TS, axis=1)  # [n_sim, TS]

        # Calculate p(action|alien) <- \sum_{TS} p(TS) * p(action|alien,TS)
        # final_p_low = softmax(beta[:, :, np.newaxis, np.newaxis] * final_Q_low, axis=3)
        final_p_low = softmax(final_Q_low, axis=3)
        p_alien_action_TS = p_TS.reshape(n_sim, n_seasons, 1, 1) * final_p_low
        p_alien_action = np.sum(p_alien_action_TS, axis=1)

    elif model_name == 'flat':
        # Flat agents select actions based on how much reward they haven gotten for this alien, averaged over seasons.

        Q_alien_action = np.mean(final_Q_low, axis=1)  # [n_sim, n_aliens, n_actions] Av. value of each action for each alien
        p_alien_action = softmax(Q_alien_action, axis=2)  # [n_sim, n_aliens, n_actions] Corresponding probabilities

    # Average over simulations
    rainbow_dat = np.mean(p_alien_action, axis=0)

    return rainbow_dat


def get_summary_rainbow(n_aliens, n_seasons, rainbow_dat, task):

    if len(rainbow_dat) == 2:  # for humans, unpack mean and se
        rainbow_dat_mean = rainbow_dat[0]
        rainbow_dat_se = rainbow_dat[1]
    else:
        rainbow_dat_mean = rainbow_dat
        rainbow_dat_se = np.zeros_like(rainbow_dat_mean)

    # Get number of choices for each TS
    def get_rainbow_summary(rainbow_dat):
        correct_actions = np.argmax(task.TS, axis=2)  # season x alien
        TS_choices = np.array([rainbow_dat[range(n_aliens), correct_actions[TSi]] for TSi in range(n_seasons)])
        TS_choices[[1, 2, 0, 2], [0, 0, 3, 3]] = np.nan  # remove actions that are correct in > 1 TS
        none_choices = (rainbow_dat[0, 0], 0, 0, rainbow_dat[3, 2])
        return np.vstack([TS_choices, none_choices])

    TS_choices = get_rainbow_summary(rainbow_dat_mean)
    summary_rainbow = np.nanmean(TS_choices, axis=1)

    TS_choices_se = get_rainbow_summary(rainbow_dat_se)
    summary_rainbow_se = np.nanmean(TS_choices_se, axis=1)

    # Visualize TS_choices
    if False:
        fig = plt.figure()
        ax = fig.add_subplot(111)
        plt.title('Rainbow phase')
        ax.bar(np.arange(4), np.sum(TS_choices, axis=1), 0.3)
        ax.set_ylabel('TS chosen (count)')
        ax.set_xticks(range(4))
        ax.set_xticklabels(['TS0', 'TS1', 'TS2', 'noTS'])
        ax.legend()

    return list(summary_rainbow) + list(summary_rainbow_se)


def get_summary_initial_learn(seasons, corrects, aliens, actions,
                              n_seasons, n_sim, trials, task):

    # Get savings (increase in accuracy from first repetition to last repetition)
    season_changes = np.array([seasons[i, 0] != seasons[i + 1, 0] for i in list(trials['1InitialLearn'])[:-1]])
    season_changes = np.insert(season_changes, 0, False)
    season_presentation = np.cumsum(season_changes)
    repetition = season_presentation // n_seasons
    n_trials_per_rep = np.sum(repetition == 0)
    n_rep_rep = np.sum(season_presentation == 0)

    corrects_rep = corrects.reshape((3, n_trials_per_rep, n_sim))
    learning_curve_rep = np.mean(corrects_rep, axis=2)
    rep_rep = learning_curve_rep.reshape((3, 3, n_rep_rep))
    rep_rep = np.mean(rep_rep, axis=1)

    saving_first_trial = rep_rep[-1, 0] - rep_rep[0, 0]  # first trial only
    saving_last_trial = rep_rep[-1, -1] - rep_rep[0, -1]  # last trial only
    saving_av = np.mean(rep_rep[-1] - rep_rep[0])  # average over all 40 trials

    savings = pd.DataFrame(data=[saving_av, saving_first_trial, saving_last_trial],
                           index=['IL_saving_av', 'IL_saving_first_trial', 'IL_saving_last_trial'])

    # Get intrusion errors (accuracy according to current TS, previous TS, and other TS)
    first_alien_new_season = aliens[season_changes][1:]  # remove very first round
    first_action_new_season = actions[season_changes][1:]  # because there is no previous TS
    first_acc_new_season = corrects[season_changes][1:]

    current_TS = seasons[season_changes][1:]
    prev_TS = seasons[season_changes][:-1]
    other_TS = 3 - current_TS - prev_TS

    first_action_new_season[first_action_new_season < 0] = np.random.choice(a=range(3))  # TODO: think about how to deal with missing values!
    acc_current_TS = task.TS[current_TS, first_alien_new_season, first_action_new_season] > 1
    # assert np.all(first_acc_new_season == acc_current_TS)
    acc_prev_TS = task.TS[prev_TS, first_alien_new_season, first_action_new_season] > 1
    acc_other_TS = task.TS[other_TS, first_alien_new_season, first_action_new_season] > 1

    intrusion_errors = pd.DataFrame(data=[np.mean(acc_current_TS), np.mean(acc_prev_TS), np.mean(acc_other_TS)],
                                    index=['IL_acc_current_TS', 'IL_acc_prev_TS', 'IL_acc_other_TS'])
    intrusion_errors_se = pd.DataFrame(data=[np.std(np.mean(acc_current_TS, axis=0)) / np.sqrt(n_sim),
                                             np.std(np.mean(acc_prev_TS, axis=0)) / np.sqrt(n_sim),
                                             np.std(np.mean(acc_other_TS, axis=0)) / np.sqrt(n_sim)],
                                       index=['IL_acc_current_TS_se', 'IL_acc_prev_TS_se', 'IL_acc_other_TS_se'])

    # Get performance index for each TS (% correct for aliens with same value in different TS)
    def get_mean_acc_for_season_alien(season, alien, another_alien=False):
        if not another_alien:
            another_alien = alien
        index = (seasons == season) & ((aliens == alien) | (aliens == another_alien))
        subj_means = np.mean(corrects[index].reshape((n_sim, int(corrects[index].shape[0]/n_sim))), axis=1)  # len=n_sim
        return [np.mean(subj_means), np.std(subj_means) / np.sqrt(len(subj_means))]  # mean, se

    Q7_mean_se = np.array(
        [get_mean_acc_for_season_alien(season=0, alien=0),  # reward == 6
         get_mean_acc_for_season_alien(season=1, alien=2),  # reward == 7
         get_mean_acc_for_season_alien(season=2, alien=0)])  # reward == 7

    Q3_mean_se = np.array(
        [get_mean_acc_for_season_alien(season=0, alien=1),  # reward == 4
         get_mean_acc_for_season_alien(season=1, alien=3),  # reward == 3
         get_mean_acc_for_season_alien(season=2, alien=1, another_alien=2)])  # reward == 3
    # Note: I'm not using aliens with reward == 2 because they all overlap with other TS (TS1->TS2; TS2->TS0)

    TS_acc = pd.DataFrame(data=np.mean(np.array([Q7_mean_se[:, 0], Q3_mean_se[:, 0]]), axis=0),
                          index=['IL_perf_TS0', 'IL_perf_TS1', 'IL_perf_TS2'])
    TS_acc_se = pd.DataFrame(data=np.mean(np.array([Q7_mean_se[:, 1], Q3_mean_se[:, 1]]), axis=0),
                             index=['IL_perf_TS0_se', 'IL_perf_TS1_se', 'IL_perf_TS2_se'])
    TS_corr = np.corrcoef(TS_acc.values.flatten(), np.arange(3))
    TS_corr = pd.DataFrame(data=[TS_corr[0, 1]], index=['IL_perf_TS_corr'])

    # Get TS choices in first few trials (like in rainbow)
    chosen_TS, chosen_TS_se = get_first_TS(seasons, aliens, actions, season_changes, task.TS, 'IL')

    return pd.concat([savings, intrusion_errors, intrusion_errors_se, TS_acc, TS_acc_se, TS_corr, chosen_TS, chosen_TS_se])


def get_first_TS(seasons, aliens, actions, season_changes, TS, phase_initial):

    """
    Gets average TS choices for just the first 4 trials after a context switch, for all subjects.
    Main work horse: get_chosen_TS()
    :param seasons:
    :param aliens:
    :param actions:
    :param season_changes:
    :param TS:
    :return: mean & se of participants' TS choices in the first four trials after context switch
    """

    # Get first four trials after context switch
    alien_sum = np.array([i // 4 for i in range(len(seasons))])
    first_trials = alien_sum[season_changes]
    first_trial_mask = np.array([np.any(alien_trial == first_trials) for alien_trial in alien_sum])

    # Subset data
    first_aliens = aliens[first_trial_mask]
    first_actions = actions[first_trial_mask]

    # Get chosen TS
    key = ('TS0', 'TS1', 'TS2', 'TS02', 'TS12', 'None')
    chosen_TS = [[get_chosen_TS(alien, action, TS, key) for alien, action in zip(first_alien, first_action)]
                 for first_alien, first_action in zip(first_aliens, first_actions)]

    # Format result
    chosen_TS_indiv = np.mean(np.array(chosen_TS), axis=0)  # average over trials to get one row per participant
    chosen_TS = pd.DataFrame(data=np.mean(chosen_TS_indiv, axis=0),
                                index=['{}_first_{}'.format(phase_initial, k) for k in key])
    chosen_TS_se = pd.DataFrame(data=np.std(chosen_TS_indiv, axis=0),
                                   index=['{}_first_{}_se'.format(phase_initial, k) for k in key])

    return chosen_TS, chosen_TS_se


def get_chosen_TS(alien, action, TS, key=('TS0', 'TS1', 'TS2', 'TS02', 'TS12', 'None')):

    """
    Tells you which TS was chosen based on a stimulus and action.
    :param alien:
    :param action:
    :param TS:
    :param key:
    :return: np.array with one column per possible TS choice as defined in key (e.g., 'TS0', 'TS1', etc.)
    """

    result = np.zeros(len(key)).astype(bool)

    correct_actions = np.argmax(TS, axis=2)  # season x alien
    TSs = np.argwhere(action == correct_actions[:, alien])

    if len(TSs) == 0:
        result[key.index('None')] = True
    if len(TSs) == 1:
        result[key.index('TS{}'.format(*TSs.flatten()))] = True
    if len(TSs) == 2:
        result[key.index('TS{}{}'.format(*TSs.flatten()))] = True

    return result


def get_summary_cloudy(seasons, corrects, aliens, actions, n_sim, task):

    # Get accuracy for trials 0 to 3 (averaged over TS)
    season_changes = np.array([seasons[i, 0] != seasons[i+1, 0] for i in range(len(seasons))[:-1]])
    season_changes = np.insert(season_changes, 0, False)
    season_presentation = np.cumsum(season_changes)
    n_rep_rep = np.sum(season_presentation == 0)

    n_first_trials = int(corrects.shape[0] / n_rep_rep)
    corrects_rep = corrects.reshape((n_first_trials, n_rep_rep, n_sim))
    subj_corrects_rep = np.mean(corrects_rep, axis=0)

    learning_curve_rep = pd.DataFrame(
        data=np.mean(subj_corrects_rep, axis=1)[:4],
        index=['CL_acc_trial0', 'CL_acc_trial1', 'CL_acc_trial2', 'CL_acc_trial3'])
    learning_curve_rep_se = np.std(subj_corrects_rep, axis=1) / np.sqrt(n_sim)
    learning_curve_rep_se = pd.DataFrame(
        data=learning_curve_rep_se[:4],
        index=['CL_acc_trial0_se', 'CL_acc_trial1_se', 'CL_acc_trial2_se', 'CL_acc_trial3_se'])

    # Get a slope for each TS
    slope = np.sum(learning_curve_rep.values.flatten() * (np.arange(4) - 1.5))

    seasons_rep = seasons.reshape((n_first_trials, n_rep_rep, n_sim))
    TS_slopes = np.zeros(3)
    for TS in range(3):
        corrects_rep_TS = corrects_rep.copy()
        corrects_rep_TS[seasons_rep != TS] = np.nan  # blank out everything that is not in this TS
        learning_curve_rep_TS = np.nanmean(corrects_rep_TS, axis=(0, 2))
        slope_TS = np.sum(learning_curve_rep_TS[:4] * (np.arange(4) - 1.5))
        TS_slopes[TS] = slope_TS

    slopes = pd.DataFrame(data=[slope] + list(TS_slopes),
                          index=['CL_slope', 'CL_slope_TS0', 'CL_slope_TS1', 'CL_slope_TS2'])

    # Get TS choices in first few trials (like in rainbow)
    chosen_TS, chosen_TS_se = get_first_TS(seasons, aliens, actions, season_changes, task.TS, 'CL')

    return pd.concat([learning_curve_rep, learning_curve_rep_se, slopes, chosen_TS, chosen_TS_se])


def read_in_human_data(human_data_path, n_trials, n_aliens, n_actions, exclude=False):

    print("Reading in human data from {}!".format(human_data_path))

    file_names = [file_name for file_name in os.listdir(human_data_path)
                  if ("pick" not in file_name) and (os.path.isfile(os.path.join(human_data_path, file_name)))]
    if exclude:
        old_n_files = len(file_names)
        file_names = [file_name for file_name in file_names if not file_name[-7:-4] in exclude]
        new_n_files = len(file_names)
        print("{0} subjects were exlcuded: {1}".format(old_n_files - new_n_files, exclude))

    n_hum = len(file_names)

    hum_seasons = np.zeros([n_trials, n_hum], dtype=int)
    hum_aliens = np.zeros([n_trials, n_hum], dtype=int)
    hum_actions = np.zeros([n_trials, n_hum], dtype=int)
    hum_rewards = np.zeros([n_trials, n_hum])
    hum_corrects = np.zeros([n_trials, n_hum])
    hum_phase = np.zeros([n_trials, n_hum])
    hum_rainbow_dat_subj = np.zeros((n_hum, n_aliens, n_actions))

    for subj, file_name in enumerate(file_names):
        subj_file = pd.read_csv(human_data_path + '/' + file_name, index_col=0).reset_index(drop=True)

        # Get feed-aliens phases
        feed_aliens_file = subj_file[
            (subj_file['phase'] == '1InitialLearning') | (subj_file['phase'] == '2CloudySeason')]
        hum_seasons[:, subj] = feed_aliens_file['TS']
        hum_aliens[:, subj] = feed_aliens_file['sad_alien']
        hum_actions[:, subj] = feed_aliens_file['item_chosen']
        hum_rewards[:, subj] = feed_aliens_file['reward']
        hum_corrects[:, subj] = feed_aliens_file['correct']
        hum_phase[:, subj] = [int(ph[0]) for ph in feed_aliens_file['phase']]

        # Get rainbow data
        rainbow_file = subj_file[(subj_file['phase'] == '5RainbowSeason')].reset_index(drop=True)
        for trial in range(rainbow_file.shape[0]):
            alien, item = rainbow_file['sad_alien'][trial], rainbow_file['item_chosen'][trial]
            if not np.isnan(item):
                hum_rainbow_dat_subj[subj, int(alien), int(item)] += 1

    hum_rainbow_dat_subj = hum_rainbow_dat_subj / np.sum(hum_rainbow_dat_subj, axis=2, keepdims=True)  # Get fractions for every subj
    hum_rainbow_dat_mean = np.mean(hum_rainbow_dat_subj, axis=0)  # Average over subjects
    hum_rainbow_dat_se = np.std(hum_rainbow_dat_subj, axis=0) / np.sqrt(n_hum)  # Average over subjects

    # Get competition data
    comp_file_names = [file_name for file_name in os.listdir(human_data_path) if "pick" in file_name]
    assert((n_hum == len(comp_file_names)), "The competition files and initial learning files are not for the same subjects!")

    hum_comp_dat = pd.DataFrame(np.zeros((n_hum, 21)))  # 21 = 3 (n_colums season) + 18 (n_columns season_alien)

    for subj, file_name in enumerate(comp_file_names):

        # Read in from disc
        subj_file = pd.read_csv(human_data_path + '/' + file_name,
                                usecols=['assess', 'id_chosen', 'id_unchosen', 'selected_better_obj'],
                                dtype={'assess': 'str', 'id_chosen': 'str', 'id_unchosen': 'str', 'selected_better_obj': 'float'}).reset_index(drop=True)
        subj_file = subj_file[np.invert(subj_file['id_unchosen'].isnull())]

        # Get season phase
        season_file = subj_file.loc[(subj_file['assess'] == 'season')]
        season_file.loc[(season_file['id_chosen'].astype(int) + season_file['id_unchosen'].astype(int)) == 1, 'choice'] = "(0, 1)"  # TODO: throws warning SettingWithCopyWarning:  A value is trying to be set on a copy of a slice from a DataFrame. Try using .loc[row_indexer,col_indexer] = value instead
        season_file.loc[(season_file['id_chosen'].astype(int) + season_file['id_unchosen'].astype(int)) == 2, 'choice'] = "(0, 2)"
        season_file.loc[(season_file['id_chosen'].astype(int) + season_file['id_unchosen'].astype(int)) == 3, 'choice'] = "(1, 2)"
        sum_season_file = season_file[['selected_better_obj', 'choice']].groupby('choice').aggregate('mean')

        # Get season-alien phase
        season_alien_file = subj_file.loc[(subj_file['assess'] == 'alien-same-season')]
        season_alien_file.loc[:, 'alien_a'] = season_alien_file['id_unchosen'].str[0].astype(int)
        season_alien_file.loc[:, 'alien_b'] = season_alien_file['id_chosen'].str[0].astype(int)
        season_alien_file.loc[:, 'choice'] = season_alien_file['id_unchosen'].str[1] + "(" +\
                                             season_alien_file[['alien_a', 'alien_b']].min(axis=1).astype(str) + ", " +\
                                             season_alien_file[['alien_a', 'alien_b']].max(axis=1).astype(str) + ")"
        sum_season_alien_file = season_alien_file[['selected_better_obj', 'choice']].groupby('choice').aggregate('mean')

        # Add all subjects together
        comp = sum_season_file.append(sum_season_alien_file)
        hum_comp_dat.loc[subj] = comp.values.flatten()
        hum_comp_dat.columns = comp.index.values
        hum_comp_dat.loc[:, '2(1, 2)'] = np.nan  # aliens 1 and 2 have the same value in TS 2 -> select better is not defined!

    return n_hum, hum_aliens, hum_seasons, hum_corrects, hum_actions, hum_rewards, (hum_rainbow_dat_mean, hum_rainbow_dat_se), hum_comp_dat


def softmax(X, axis=None):
    """
    Compute the softmax of each element along an axis of X.

    Parameters
    ----------
    X: ND-Array. Probably should be floats.
    theta (optional): float parameter, used as a multiplier
        prior to exponentiation. Default = 1.0
    axis (optional): axis to compute values along. Default is the
        first non-singleton axis.

    Returns an array the same size as X. The result will sum to 1
    along the specified axis.
    """

    # make X at least 2d
    y = np.atleast_2d(X)

    # find axis
    if axis is None:
        axis = next(j[0] for j in enumerate(y.shape) if j[1] > 1)

    # subtract the max for numerical stability
    y = y - np.expand_dims(np.max(y, axis=axis), axis)

    # exponentiate y
    y = np.exp(y)

    # take the sum along the specified axis
    ax_sum = np.expand_dims(np.sum(y, axis=axis), axis)

    # finally: divide elementwise
    p = y / ax_sum

    # flatten if X was 1D
    if len(X.shape) == 1: p = p.flatten()

    return p
